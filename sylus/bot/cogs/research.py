import discord
from discord.ext import commands
from sqlalchemy import select

from sylus.db.base import get_session
from sylus.db.models import Nation
from sylus.services.research import (
    get_all_tech_definitions,
    get_available_techs,
    queue_technology,
    cancel_research,
    create_tech_license,
    format_progress_bar,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


class ResearchCog(commands.Cog):
    """Cog handling technology trees, research queue management, and tech licensing."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    research = discord.SlashCommandGroup("research", "Technology research, queues, and tech licenses")

    async def _tech_id_autocomplete(self, ctx: discord.AutocompleteContext):
        all_techs = get_all_tech_definitions()
        query = ctx.value.lower() if ctx.value else ""
        results = []
        for t_id, t_info in all_techs.items():
            disp = f"{t_info['name']} ({t_id})"
            if query in t_id.lower() or query in t_info["name"].lower():
                results.append(discord.OptionChoice(name=disp[:100], value=t_id))
            if len(results) >= 25:
                break
        return results

    @research.command(name="tree", description="Browse tech trees with visual progress bars and filters.")
    async def tree(
        self,
        ctx: discord.ApplicationContext,
        tree_name: str = discord.Option(
            str,
            "Select tree filter",
            choices=["all", "military", "economy", "community", "industry", "energy", "espionage", "space_nuclear"],
            default="all",
        ),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            filter_tree = None if tree_name == "all" else tree_name
            techs = await get_available_techs(session, nat.id, tree_filter=filter_tree)

            embed = discord.Embed(
                title=f"Tech Tree - {tree_name.title()}",
                description=f"Technology tree progress for **{nat.name}**",
                color=discord.Color.blue(),
            )

            # Group techs by tree/category
            grouped = {}
            for t in techs:
                cat = f"{t['tree_name']} ({t['category']})" if t['category'] != t['tree_name'] else t['tree_name']
                grouped.setdefault(cat, []).append(t)

            for cat_name, items in grouped.items():
                lines = []
                for item in items[:8]:  # Limit lines per field for Embed size constraints
                    status_icon = "✅" if item["status"] == "UNLOCKED" else "⏳" if item["status"] == "IN_QUEUE" else "🔓" if item["status"] == "AVAILABLE" else "🔒"
                    line = f"{status_icon} **{item['name']}** (`{item['tech_id']}`) - Cost: {item['rp_cost']:.0f} RP"
                    if item["status"] == "IN_QUEUE":
                        line += f"\n└ {item['progress_bar']} ({item['allocated_rp']:.0f}/{item['target_rp']:.0f} RP)"
                    lines.append(line)

                embed.add_field(name=cat_name, value="\n".join(lines) if lines else "None", inline=False)

            await ctx.respond(embed=embed)

    @research.command(name="queue", description="Queue a technology for research.")
    async def queue(
        self,
        ctx: discord.ApplicationContext,
        tech_id: str = discord.Option(str, "Technology ID to research", autocomplete=_tech_id_autocomplete),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            try:
                q = await queue_technology(session, nat, tech_id)
                all_techs = get_all_tech_definitions()
                t_info = all_techs[tech_id]
                await ctx.respond(
                    f"🔬 Added **{t_info['name']}** (`{tech_id}`) to research queue at position **#{q.queue_position}**."
                )
            except Exception as e:
                await ctx.respond(f"⚠️ Unable to queue research: {e}", ephemeral=True)

    @research.command(name="cancel", description="Cancel queued research and receive RP refund.")
    async def cancel(
        self,
        ctx: discord.ApplicationContext,
        queue_id: int = discord.Option(int, "Research queue item ID to cancel"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            try:
                refunded = await cancel_research(session, nat, queue_id)
                await ctx.respond(
                    f"❌ Canceled research queue item **#{queue_id}**. Refunded **{refunded:.1f} RP** to research ledger."
                )
            except Exception as e:
                await ctx.respond(f"⚠️ Unable to cancel research: {e}", ephemeral=True)

    @research.command(name="status", description="View current nation research queue and progress.")
    async def status(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            techs = await get_available_techs(session, nat.id)
            queued = [t for t in techs if t["status"] == "IN_QUEUE"]
            unlocked = [t for t in techs if t["status"] == "UNLOCKED"]

            embed = discord.Embed(
                title=f"Research Status: {nat.name}",
                color=discord.Color.teal(),
            )
            embed.add_field(name="Unlocked Technologies", value=str(len(unlocked)), inline=True)
            embed.add_field(name="Queued Projects", value=str(len(queued)), inline=True)

            if queued:
                q_lines = []
                for q in sorted(queued, key=lambda x: x["queue_position"]):
                    bar = q["progress_bar"]
                    q_lines.append(
                        f"**#{q['queue_position']} {q['name']}** (`{q['tech_id']}`)\n└ {bar} ({q['allocated_rp']:.0f}/{q['target_rp']:.0f} RP)"
                    )
                embed.add_field(name="Active Research Queue", value="\n\n".join(q_lines), inline=False)
            else:
                embed.add_field(name="Active Research Queue", value="Queue is empty. Use `/research queue` to start.", inline=False)

            await ctx.respond(embed=embed)

    @research.command(name="license", description="Grant a tech-license to another nation.")
    async def license(
        self,
        ctx: discord.ApplicationContext,
        target_user: discord.User = discord.Option(discord.User, "Target nation owner"),
        tech_id: str = discord.Option(str, "Technology ID to license", autocomplete=_tech_id_autocomplete),
        royalty_per_turn: float = discord.Option(float, "Royalty fee per turn ($)", default=0.0),
    ):
        await ctx.defer()
        async with get_session() as session:
            licensor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not licensor:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            licensee = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not licensee:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            try:
                lic = await create_tech_license(session, licensor, licensee, tech_id, royalty_per_turn)
                all_techs = get_all_tech_definitions()
                t_name = all_techs[tech_id]["name"]
                await ctx.respond(
                    f"📜 Granted tech-license for **{t_name}** (`{tech_id}`) to **{licensee.name}** "
                    f"with royalty fee of **${lic.royalty_per_turn:,.2f}/turn**."
                )
            except Exception as e:
                await ctx.respond(f"⚠️ License failed: {e}", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(ResearchCog(bot))
