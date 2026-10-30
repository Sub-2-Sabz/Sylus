import io
import json
import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup

from sylus.db.base import get_session
from sylus.engine.turn import get_or_create_global_state, export_snapshot, restore_snapshot
from sylus.services.contract import admin_resolve_appeal
from sylus.logging import get_logger

logger = get_logger(__name__)


class AdminCog(commands.Cog):
    """Cog for administrative control of the turn engine and server configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    admin_group = SlashCommandGroup("admin", "Admin management commands")
    channels_group = admin_group.create_subgroup("channels", "Configure admin notification channels")

    @channels_group.command(name="set_map", description="Set map and turn summary channel")
    async def set_map(self, ctx: discord.ApplicationContext, channel: discord.TextChannel):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            state = await get_or_create_global_state(session)
            state.map_channel_id = channel.id
            await session.commit()
        await ctx.respond(f"✅ Map & summary channel updated to {channel.mention}.", ephemeral=True)

    @channels_group.command(name="set_backup", description="Set private backup channel")
    async def set_backup(self, ctx: discord.ApplicationContext, channel: discord.TextChannel):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            state = await get_or_create_global_state(session)
            state.backup_channel_id = channel.id
            await session.commit()
        await ctx.respond(f"✅ Backup channel updated to {channel.mention}.", ephemeral=True)

    @admin_group.command(name="pause", description="Pause automated turn processing")
    async def pause(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            state = await get_or_create_global_state(session)
            state.is_paused = True
            await session.commit()
        await ctx.respond("⏸️ Turn engine paused.", ephemeral=True)

    @admin_group.command(name="resume", description="Resume automated turn processing")
    async def resume(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            state = await get_or_create_global_state(session)
            state.is_paused = False
            await session.commit()

        scheduler = getattr(self.bot, "turn_scheduler", None)
        if scheduler:
            scheduler._wake_event.set()
        await ctx.respond("▶️ Turn engine resumed.", ephemeral=True)

    @admin_group.command(name="force_turn", description="Force immediate turn execution")
    async def force_turn(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=False)
        scheduler = getattr(self.bot, "turn_scheduler", None)
        if scheduler:
            result = await scheduler.force_turn()
            if result:
                await ctx.respond(f"⚡ Forced Turn **{result.turn_number}** executed successfully.")
                return
        await ctx.respond("❌ Failed to execute forced turn or turn scheduler unavailable.")

    @admin_group.command(name="sync_commands", description="Force re-syncing slash commands with Discord API")
    async def sync_commands(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        from sylus.bot.bot import sync_commands_if_changed
        try:
            synced = await sync_commands_if_changed(self.bot, force=True)
            await ctx.respond("🔄 Slash commands forced sync completed successfully.", ephemeral=True)
        except Exception as e:
            logger.error("Admin sync_commands failed", error=str(e))
            await ctx.respond(f"❌ Failed to sync slash commands: {e}", ephemeral=True)

    @admin_group.command(name="contract_override", description="Admin override resolution for contract appeals")
    async def contract_override(
        self,
        ctx: discord.ApplicationContext,
        appeal_id: int = discord.Option(int, "Appeal ID"),
        uphold: bool = discord.Option(bool, "Uphold appeal (True) or reject (False)"),
        notes: str = discord.Option(str, "Admin arbitration notes", default=""),
    ):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            try:
                c = await admin_resolve_appeal(session, appeal_id, ctx.author.id, uphold, notes)
                await session.commit()
                status_str = "UPHELD (Contract restored to active)" if uphold else "REJECTED (Penalty enforced)"
                await ctx.respond(f"⚖️ Resolved Appeal **#{appeal_id}**: `{status_str}` for Contract **#{c.id}**.", ephemeral=True)
            except Exception as e:
                await ctx.respond(f"⚠️ Appeal override failed: {e}", ephemeral=True)

    @admin_group.command(name="backup", description="Create and export database snapshot")
    async def backup(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            snapshot_data = await export_snapshot(session)

        snapshot_bytes = json.dumps(snapshot_data, indent=2).encode("utf-8")
        file_obj = discord.File(io.BytesIO(snapshot_bytes), filename="sylus_manual_backup.json")
        await ctx.respond("📦 Snapshot backup created:", file=file_obj, ephemeral=True)

    @admin_group.command(name="restore", description="Restore database state from uploaded snapshot JSON file")
    async def restore(self, ctx: discord.ApplicationContext, attachment: discord.Attachment):
        await ctx.defer(ephemeral=True)
        try:
            content = await attachment.read()
            snapshot_data = json.loads(content.decode("utf-8"))
            async with get_session() as session:
                await restore_snapshot(session, snapshot_data)
            await ctx.respond("✅ State restored successfully from snapshot.", ephemeral=True)
        except Exception as e:
            logger.error("Failed to restore snapshot", error=str(e))
            await ctx.respond(f"❌ Failed to restore snapshot: {str(e)}", ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(AdminCog(bot))
