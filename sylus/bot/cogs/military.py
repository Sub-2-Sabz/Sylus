from typing import Optional
import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup, option
from sqlalchemy import select

from sylus.db.base import get_session
from sylus.db.models import Nation, MilitaryQueue, GlobalState
from sylus.services.military_production import (
    enqueue_military_production,
    cancel_military_queue,
    recruit_manpower,
    conduct_spy_mission,
    get_visible_forces,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


class MilitaryCog(commands.Cog):
    """Military production, logistics, manpower, and intelligence commands."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    military = SlashCommandGroup("military", "View and manage military forces, production, and intelligence")

    @military.command(name="forces", description="View active military forces or spied enemy forces.")
    @option("target_nation", str, description="Target nation name (leave blank for your own forces)", required=False)
    async def forces(self, ctx: discord.ApplicationContext, target_nation: Optional[str] = None):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            stmt = select(Nation).where(Nation.discord_user_id == ctx.author.id)
            res = await session.execute(stmt)
            own_nation = res.scalar_one_or_none()

            if not own_nation:
                return await ctx.respond("You must create a nation first using `/nation create`.", ephemeral=True)

            target_id = own_nation.id
            target_name = own_nation.name

            if target_nation and target_nation.strip():
                t_stmt = select(Nation).where(Nation.name.ilike(target_nation.strip()))
                t_res = await session.execute(t_stmt)
                tn = t_res.scalar_one_or_none()
                if not tn:
                    return await ctx.respond(f"Target nation '{target_nation}' not found.", ephemeral=True)
                target_id = tn.id
                target_name = tn.name

            g_stmt = select(GlobalState.turn_number).where(GlobalState.id == 1)
            g_res = await session.execute(g_stmt)
            curr_turn = g_res.scalar() or 1

            visible = await get_visible_forces(session, own_nation.id, target_id, curr_turn)

            embed = discord.Embed(
                title=f"Military Forces - {target_name}",
                color=discord.Color.dark_red(),
            )
            embed.add_field(name="Intel Level", value=f"{int(visible['intel_level'] * 100)}%", inline=True)
            embed.add_field(name="Fog of War", value="Active" if visible["fog_of_war_active"] else "Inactive", inline=True)

            formations = visible["formations"]
            if not formations:
                embed.description = "No active military formations found."
            else:
                desc_lines = []
                for f in formations[:10]:  # Limit display items
                    if visible["fog_of_war_active"]:
                        desc_lines.append(f"• **Province #{f['province_id']}**: {f['category']} - Qty: {f['quantity_estimate']}")
                    else:
                        desc_lines.append(
                            f"• **{f['design_name']}** (Prov #{f['province_id']}) - Qty: {f['quantity']} | "
                            f"Morale: {int(f['morale']*100)}% | Exp: {int(f['experience']*100)}% | "
                            f"Fuel: {int(f['fuel_status']*100)}% | Ammo: {int(f['ammo_status']*100)}%"
                        )
                embed.description = "\n".join(desc_lines)

            await ctx.respond(embed=embed, ephemeral=True)

    @military.command(name="recruit", description="Recruit unemployed citizens into active military soldiers.")
    @option("quantity", int, description="Number of soldiers to recruit", required=True)
    async def recruit(self, ctx: discord.ApplicationContext, quantity: int):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            stmt = select(Nation).where(Nation.discord_user_id == ctx.author.id)
            res = await session.execute(stmt)
            nation = res.scalar_one_or_none()

            if not nation:
                return await ctx.respond("You must create a nation first using `/nation create`.", ephemeral=True)

            try:
                updated = await recruit_manpower(session, nation.id, quantity)
                await ctx.respond(
                    f"Recruited **{quantity:,}** soldiers. Current military personnel: **{updated.soldiers:,}** (Unemployed remaining: **{updated.unemployed:,}**).",
                    ephemeral=True
                )
            except ValueError as e:
                await ctx.respond(f"Recruitment failed: {e}", ephemeral=True)

    @military.command(name="produce", description="Enqueue unit production in a province facility.")
    @option("province_id", int, description="ID of the province with factory/shipyard/airbase", required=True)
    @option("design_id", int, description="ID of the saved unit design", required=True)
    @option("quantity", int, description="Quantity of units to produce", default=1)
    async def produce(self, ctx: discord.ApplicationContext, province_id: int, design_id: int, quantity: int):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            stmt = select(Nation).where(Nation.discord_user_id == ctx.author.id)
            res = await session.execute(stmt)
            nation = res.scalar_one_or_none()

            if not nation:
                return await ctx.respond("You must create a nation first using `/nation create`.", ephemeral=True)

            try:
                q_item = await enqueue_military_production(session, nation.id, province_id, design_id, quantity)
                await ctx.respond(
                    f"Enqueued **{quantity}x** unit production (Queue #{q_item.id}) in Province #{province_id}. Build time: **{q_item.turns_remaining} turn(s)**.",
                    ephemeral=True
                )
            except ValueError as e:
                await ctx.respond(f"Production failed: {e}", ephemeral=True)

    @military.command(name="queue", description="View active military production queues.")
    async def queue(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            stmt = select(Nation).where(Nation.discord_user_id == ctx.author.id)
            res = await session.execute(stmt)
            nation = res.scalar_one_or_none()

            if not nation:
                return await ctx.respond("You must create a nation first using `/nation create`.", ephemeral=True)

            q_stmt = select(MilitaryQueue).where(MilitaryQueue.nation_id == nation.id)
            q_res = await session.execute(q_stmt)
            queues = q_res.scalars().all()

            if not queues:
                return await ctx.respond("No active military production queues.", ephemeral=True)

            embed = discord.Embed(title=f"Military Production Queues - {nation.name}", color=discord.Color.blue())
            for item in queues:
                embed.add_field(
                    name=f"Queue #{item.id} (Province #{item.province_id})",
                    value=f"Design #{item.design_id} | Qty: {item.quantity} | Facility: {item.facility_type.title()} | Turns left: {item.turns_remaining}",
                    inline=False
                )
            await ctx.respond(embed=embed, ephemeral=True)

    @military.command(name="cancel", description="Cancel queued military production and refund resources.")
    @option("queue_id", int, description="ID of the production queue item to cancel", required=True)
    async def cancel(self, ctx: discord.ApplicationContext, queue_id: int):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            stmt = select(Nation).where(Nation.discord_user_id == ctx.author.id)
            res = await session.execute(stmt)
            nation = res.scalar_one_or_none()

            if not nation:
                return await ctx.respond("You must create a nation first using `/nation create`.", ephemeral=True)

            success = await cancel_military_queue(session, nation.id, queue_id)
            if success:
                await ctx.respond(f"Successfully cancelled queue item #{queue_id} and refunded resources.", ephemeral=True)
            else:
                await ctx.respond(f"Queue item #{queue_id} not found or not owned by your nation.", ephemeral=True)

    @military.command(name="spy", description="Conduct espionage mission on an enemy nation.")
    @option("target_nation", str, description="Name of the target nation to spy on", required=True)
    async def spy(self, ctx: discord.ApplicationContext, target_nation: str):
        await ctx.defer(ephemeral=True)
        async with get_session() as session:
            stmt = select(Nation).where(Nation.discord_user_id == ctx.author.id)
            res = await session.execute(stmt)
            own_nation = res.scalar_one_or_none()

            if not own_nation:
                return await ctx.respond("You must create a nation first using `/nation create`.", ephemeral=True)

            t_stmt = select(Nation).where(Nation.name.ilike(target_nation.strip()))
            t_res = await session.execute(t_stmt)
            tn = t_res.scalar_one_or_none()

            if not tn:
                return await ctx.respond(f"Target nation '{target_nation}' not found.", ephemeral=True)

            g_stmt = select(GlobalState.turn_number).where(GlobalState.id == 1)
            g_res = await session.execute(g_stmt)
            curr_turn = g_res.scalar() or 1

            try:
                intel = await conduct_spy_mission(session, own_nation.id, tn.id, curr_turn)
                await ctx.respond(
                    f"Espionage mission against **{tn.name}** successful! Intel level increased to **{int(intel.intel_level * 100)}%** (Expires at turn {intel.expires_at_turn}).",
                    ephemeral=True
                )
            except ValueError as e:
                await ctx.respond(f"Spy mission failed: {e}", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(MilitaryCog(bot))
