import discord
from discord.ext import commands
from sqlalchemy import select

from sylus.db.base import get_session
from sylus.db.models import Nation, Province, UnitDesign, GlobalState
from sylus.services.province_search import get_province_index, province_autocomplete
from sylus.services.military_logistics import (
    enqueue_unit_production,
    list_production_queue,
    cancel_production_queue,
    train_soldiers,
    resupply_formations,
    spy_on_nation,
    get_visible_nation_forces,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


class MilitaryCog(commands.Cog):
    """Cog handling military force management, production queues, logistics, and Fog of War espionage."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    military = discord.SlashCommandGroup("military", "View and manage military forces, production, and espionage")

    @military.command(name="build", description="Enqueue unit production in a province facility.")
    async def build_unit(
        self,
        ctx: discord.ApplicationContext,
        province_name: str = discord.Option(str, "Province name to construct units in", autocomplete=province_autocomplete),
        design_id: int = discord.Option(int, "Unit Model Design ID"),
        quantity: int = discord.Option(int, "Quantity to produce", default=1),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            prov_stmt = select(Province).where(Province.nation_id == nat.id, Province.name.ilike(province_name.strip()))
            prov = (await session.execute(prov_stmt)).scalar_one_or_none()
            if not prov:
                await ctx.respond(f"Province '{province_name}' not found or not owned by your nation.", ephemeral=True)
                return

            try:
                queue_item = await enqueue_unit_production(session, nat.id, prov.id, design_id, quantity)
                design = await session.get(UnitDesign, design_id)
                design_name = design.name if design else f"Model #{design_id}"

                embed = discord.Embed(
                    title="🏭 Military Production Enqueued",
                    description=f"Enqueued **{quantity}x {design_name}** at facility in **{prov.name}**.",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Queue ID", value=f"#{queue_item.id}", inline=True)
                embed.add_field(name="Build Time", value=f"{queue_item.turns_remaining} turn(s)", inline=True)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Production failed: {e}", ephemeral=True)

    @military.command(name="queue", description="View active military production queues for your nation.")
    async def view_queue(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            items = await list_production_queue(session, nat.id)
            embed = discord.Embed(
                title=f"📋 Military Production Queues: {nat.name}",
                color=discord.Color.blue(),
            )
            if not items:
                embed.description = "No active unit production queues."
            else:
                lines = []
                for item in items:
                    design = await session.get(UnitDesign, item.design_id)
                    prov = await session.get(Province, item.province_id)
                    d_name = design.name if design else f"Model #{item.design_id}"
                    p_name = prov.display_name if prov and prov.display_name else (prov.name if prov else f"Province #{item.province_id}")
                    lines.append(f"• **#{item.id}** `{item.quantity}x {d_name}` in **{p_name}** ({item.facility_type}) — ⏳ **{item.turns_remaining} turn(s)** remaining")
                embed.description = "\n".join(lines)

            await ctx.respond(embed=embed)

    @military.command(name="cancel", description="Cancel a queued military unit batch and refund partial resources.")
    async def cancel_queue(
        self,
        ctx: discord.ApplicationContext,
        queue_id: int = discord.Option(int, "Production Queue Item ID to cancel"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            success = await cancel_production_queue(session, nat.id, queue_id)
            if success:
                await ctx.respond(f"🗑️ Successfully cancelled production queue batch **#{queue_id}**.")
            else:
                await ctx.respond(f"⚠️ Unable to cancel queue batch #{queue_id}. Ensure it exists and belongs to you.", ephemeral=True)

    @military.command(name="forces", description="View active military formations, morale, and supply status.")
    async def view_forces(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            intel_lvl, forces = await get_visible_nation_forces(session, nat.id, nat.id)
            embed = discord.Embed(
                title=f"🎖️ Military Formations & Forces: {nat.name}",
                description=f"🪖 **Available Soldiers (Manpower):** {nat.soldiers:,}",
                color=discord.Color.gold(),
            )
            if not forces:
                embed.add_field(name="Formations", value="No active deployed military formations.", inline=False)
            else:
                lines = []
                for f in forces:
                    fuel_pct = int(f["fuel_supply"] * 100)
                    ammo_pct = int(f["ammo_supply"] * 100)
                    lines.append(
                        f"• **#{f['formation_id']}** `{f['quantity']}x {f['design_name']}` @ **{f['province_name']}**\n"
                        f"  ❤️ Morale: **{f['morale']:.0f}%** | 🏆 Exp: **{f['experience']:.0f}** | ⛽ Fuel: **{fuel_pct}%** | 🪖 Ammo: **{ammo_pct}%**"
                    )
                embed.add_field(name="Deployed Formations", value="\n".join(lines), inline=False)

            await ctx.respond(embed=embed)

    @military.command(name="train", description="Train unemployed population into soldiers (manpower).")
    async def train_manpower(
        self,
        ctx: discord.ApplicationContext,
        quantity: int = discord.Option(int, "Number of soldiers to train"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            success, msg = await train_soldiers(session, nat.id, quantity)
            if success:
                await ctx.respond(f"🪖 {msg}")
            else:
                await ctx.respond(f"⚠️ Training failed: {msg}", ephemeral=True)

    @military.command(name="supply", description="Resupply fuel and ammo to active military forces from national stockpiles.")
    async def supply_forces(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            success, msg = await resupply_formations(session, nat.id)
            if success:
                await ctx.respond(f"⛽ {msg}")
            else:
                await ctx.respond(f"⚠️ Resupply failed: {msg}", ephemeral=True)

    @military.command(name="inspect", description="Inspect another nation's military forces (subject to Fog of War).")
    async def inspect_nation(
        self,
        ctx: discord.ApplicationContext,
        target_user: discord.User = discord.Option(discord.User, "Target nation leader"),
    ):
        await ctx.defer()
        async with get_session() as session:
            viewer = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not viewer:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            target = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not target:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            intel_lvl, forces = await get_visible_nation_forces(session, viewer.id, target.id)
            embed = discord.Embed(
                title=f"🕵️ Military Intelligence: {target.name}",
                description=f"**Intel Level:** `{intel_lvl}` ({'Full Visibility' if intel_lvl >= 2 else 'Obfuscated by Fog of War'})",
                color=discord.Color.dark_purple() if intel_lvl < 2 else discord.Color.green(),
            )

            if not forces:
                embed.add_field(name="Detected Forces", value="No detected military formations.", inline=False)
            else:
                lines = []
                for f in forces:
                    if f["fog_of_war"]:
                        lines.append(f"• **Location:** {f['province_name']} | **Unit:** `{f['design_name']}` | **Est. Strength:** `{f['quantity_range']}`")
                    else:
                        fuel_pct = int(f["fuel_supply"] * 100)
                        ammo_pct = int(f["ammo_supply"] * 100)
                        lines.append(
                            f"• `{f['quantity']}x {f['design_name']}` @ **{f['province_name']}**\n"
                            f"  Morale: **{f['morale']:.0f}%** | Exp: **{f['experience']:.0f}** | Fuel: **{fuel_pct}%** | Ammo: **{ammo_pct}%**"
                        )
                embed.add_field(name="Military Formations", value="\n".join(lines), inline=False)

            if intel_lvl < 2:
                embed.set_footer(text="Use `/military spy @leader` to execute an espionage operation and lift Fog of War.")

            await ctx.respond(embed=embed)

    @military.command(name="spy", description="Execute an espionage mission against a nation to lift Fog of War.")
    async def spy_mission(
        self,
        ctx: discord.ApplicationContext,
        target_user: discord.User = discord.Option(discord.User, "Target nation leader"),
    ):
        await ctx.defer()
        async with get_session() as session:
            viewer = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not viewer:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            target = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not target:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            success, msg = await spy_on_nation(session, viewer.id, target.id)
            if success:
                await ctx.respond(f"🕵️ {msg}")
            else:
                await ctx.respond(f"⚠️ Espionage mission failed: {msg}", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(MilitaryCog(bot))
