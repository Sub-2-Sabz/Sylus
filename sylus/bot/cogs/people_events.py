import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.base import get_session
from sylus.db.models import Nation, DisasterZone, NationEvent, Province
from sylus.services.demographics import apply_unrest_response
from sylus.services.events import resolve_event_choice
from sylus.logging import get_logger

logger = get_logger(__name__)


class PeopleEventsCog(commands.Cog):
    """Cog handling population demographics, unrest responses, active disasters, and narrative events."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    people = discord.SlashCommandGroup("people", "Demographics and unrest management")
    disasters_group = discord.SlashCommandGroup("disasters", "Active disasters and hazard zones")
    event_group = discord.SlashCommandGroup("event", "Narrative events and decisions")

    @people.command(name="status", description="View population demographics, stats, and unrest level.")
    async def status(self, ctx: discord.ApplicationContext, user: discord.User = discord.Option(discord.User, "Target user", default=None)):
        await ctx.defer()
        target_user = user or ctx.author
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond(f"No nation found for {target_user.mention}.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Demographics & Society: {nat.name}",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Population", value=f"{nat.population:,}", inline=True)
            embed.add_field(name="Unrest Level", value=nat.unrest_level.upper(), inline=True)
            embed.add_field(name="Happiness", value=f"{nat.happiness * 100:.1f}%", inline=True)

            embed.add_field(name="Health", value=f"{nat.health * 100:.1f}%", inline=True)
            embed.add_field(name="Education", value=f"{nat.education * 100:.1f}%", inline=True)
            embed.add_field(name="Crime Rate", value=f"{nat.crime * 100:.1f}%", inline=True)

            embed.add_field(name="Pollution", value=f"{nat.pollution * 100:.1f}%", inline=True)
            embed.add_field(name="Corruption", value=f"{nat.corruption * 100:.1f}%", inline=True)
            embed.add_field(name="War Support", value=f"{nat.war_support * 100:.1f}%", inline=True)

            embed.add_field(
                name="Workforce Breakdown",
                value=f"Workers: {nat.workers:,} | Soldiers: {nat.soldiers:,} | Unemployed: {nat.unemployed:,}",
                inline=False,
            )
            await ctx.respond(embed=embed)

    @people.command(name="response", description="Respond to unrest with policy reforms, concessions, or crackdowns.")
    async def response(
        self,
        ctx: discord.ApplicationContext,
        response_type: str = discord.Option(
            str,
            "Response action",
            choices=["reforms", "concessions", "police_control", "propaganda", "military_crackdown"],
        ),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                res = await apply_unrest_response(session, nat.id, response_type)
                embed = discord.Embed(
                    title=f"Unrest Response Executed: {response_type.title()}",
                    description=f"Action successfully applied to **{nat.name}**.",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Cost (Money)", value=f"${res['cost_money']:,.2f}", inline=True)
                embed.add_field(name="New Unrest Level", value=res["unrest_level"].upper(), inline=True)
                embed.add_field(name="New Happiness", value=f"{res['happiness'] * 100:.1f}%", inline=True)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Response failed: {e}", ephemeral=True)

    @disasters_group.command(name="active", description="View active disaster zones.")
    async def active_disasters(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            dz_res = await session.execute(select(DisasterZone))
            zones = dz_res.scalars().all()

            if not zones:
                await ctx.respond("🌍 No active disaster zones reported across the world.")
                return

            prov_res = await session.execute(select(Province))
            provs = {p.id: p for p in prov_res.scalars().all()}

            embed = discord.Embed(title="🚨 Active Global Disaster Zones", color=discord.Color.red())
            lines = []
            for z in zones:
                p_name = provs[z.province_id].name if z.province_id in provs else f"Province #{z.province_id}"
                lines.append(f"• **{z.disaster_type.title()}** in **{p_name}** ({z.turns_remaining} turn(s) remaining)")

            embed.description = "\n".join(lines)
            await ctx.respond(embed=embed)

    @event_group.command(name="list", description="View pending narrative events for your nation.")
    async def event_list(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            ev_res = await session.execute(
                select(NationEvent).where(NationEvent.nation_id == nat.id, NationEvent.status == "pending")
            )
            events = ev_res.scalars().all()

            if not events:
                await ctx.respond("📜 No pending narrative events at this time.")
                return

            embed = discord.Embed(title=f"Pending Events: {nat.name}", color=discord.Color.gold())
            for ev in events:
                choices_text = []
                for idx, c in enumerate(ev.choices):
                    choices_text.append(f"  [{idx}] {c.get('label')}")

                val_text = f"{ev.description}\n**Choices:**\n" + "\n".join(choices_text)
                embed.add_field(name=f"Event #{ev.id}: {ev.title}", value=val_text, inline=False)

            await ctx.respond(embed=embed)

    @event_group.command(name="choose", description="Make a choice for a pending narrative event.")
    async def event_choose(
        self,
        ctx: discord.ApplicationContext,
        event_id: int = discord.Option(int, "Event ID from /event list"),
        choice_index: int = discord.Option(int, "Choice index e.g. 0 or 1"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                res = await resolve_event_choice(session, nat.id, event_id, choice_index)
                embed = discord.Embed(
                    title="Narrative Event Resolved",
                    description=f"Option **'{res['chosen_label']}'** was chosen.",
                    color=discord.Color.green(),
                )
                fx_lines = [f"• {k.title()}: {v}" for k, v in res["effects_applied"].items()]
                embed.add_field(name="Effects Applied", value="\n".join(fx_lines) if fx_lines else "None", inline=False)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Event choice failed: {e}", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(PeopleEventsCog(bot))
