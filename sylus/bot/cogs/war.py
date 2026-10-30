import discord
from discord.ext import commands
from sqlalchemy import select, or_

from sylus.db.base import get_session
import io
from sylus.db.models import Nation, Province, GlobalState, War, WarLog
from sylus.db.war_models import ProvinceOccupation, PeaceTreaty
from sylus.services.war import declare_war, execute_war_action
from sylus.services.peace_treaty import create_peace_treaty, accept_peace_treaty
from sylus.map.renderer import MapRenderer, ASSETS_DIR
from sylus.logging import get_logger

logger = get_logger(__name__)


class WarCog(commands.Cog):
    """Cog handling war declarations, action point combat execution, ceasefire offers, and war log embeds."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    war = discord.SlashCommandGroup("war", "Declare war, execute combat actions, and manage active conflict")

    @war.command(name="declare", description="Declare war on another nation.")
    async def declare(
        self,
        ctx: discord.ApplicationContext,
        target_user: discord.User = discord.Option(discord.User, "Target nation leader"),
        casus_belli: str = discord.Option(
            str, "Casus Belli reason",
            choices=["territorial_claim", "border_dispute", "aggressor", "retaliation", "broken_contract", "none"],
            default="none"
        ),
    ):
        await ctx.defer()
        async with get_session() as session:
            attacker = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not attacker:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            defender = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not defender:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            gs = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            current_turn = gs.turn_number if gs else 1

            try:
                new_war = await declare_war(session, attacker.id, defender.id, casus_belli, current_turn)
                embed = discord.Embed(
                    title="⚔️ War Declared!",
                    description=f"**{attacker.name}** has declared war on **{defender.name}**!",
                    color=discord.Color.red(),
                )
                embed.add_field(name="War ID", value=f"#{new_war.id}", inline=True)
                embed.add_field(name="Casus Belli", value=f"`{casus_belli}`", inline=True)
                embed.add_field(name="Action Points", value=f"⚡ {new_war.attacker_ap} AP", inline=True)
                if casus_belli == "none":
                    embed.add_field(name="⚠️ Stability Penalty", value="Unprovoked war incurs stability and reputation penalties.", inline=False)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ War declaration failed: {e}", ephemeral=True)

    @war.command(name="action", description="Execute a military action in an active war.")
    async def action(
        self,
        ctx: discord.ApplicationContext,
        war_id: int = discord.Option(int, "War ID"),
        action_type: str = discord.Option(
            str, "Action type",
            choices=["ground_attack", "air_strike", "naval_attack", "missile_launch", "airlift", "blockade", "nuclear_strike", "ceasefire_offer"]
        ),
        province_name: str = discord.Option(str, "Target province name (optional)", default=""),
    ):
        await ctx.defer()
        async with get_session() as session:
            actor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not actor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            gs = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            current_turn = gs.turn_number if gs else 1

            target_prov = None
            if province_name.strip():
                prov_stmt = select(Province).where(Province.name.ilike(province_name.strip()))
                target_prov = (await session.execute(prov_stmt)).scalar_one_or_none()

            try:
                war_log = await execute_war_action(
                    session, war_id, actor.id, action_type,
                    province_id=target_prov.id if target_prov else None,
                    current_turn=current_turn
                )
                embed = _build_war_log_embed(war_log, actor.name)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Action failed: {e}", ephemeral=True)

    @war.command(name="ceasefire", description="Offer or accept a ceasefire peace offer.")
    async def ceasefire(
        self,
        ctx: discord.ApplicationContext,
        war_id: int = discord.Option(int, "War ID"),
    ):
        await ctx.defer()
        async with get_session() as session:
            actor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not actor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            gs = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            current_turn = gs.turn_number if gs else 1

            try:
                war_log = await execute_war_action(session, war_id, actor.id, "ceasefire_offer", current_turn=current_turn)
                embed = _build_war_log_embed(war_log, actor.name)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Ceasefire failed: {e}", ephemeral=True)

    @war.command(name="list", description="List active wars and beige protection periods.")
    async def list_wars(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            actor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not actor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            stmt = select(War).where(
                War.status.in_(["active", "beige"]),
                or_(War.attacker_id == actor.id, War.defender_id == actor.id)
            )
            wars = (await session.execute(stmt)).scalars().all()

            embed = discord.Embed(title=f"⚔️ Conflicts involving {actor.name}", color=discord.Color.dark_red())
            if not wars:
                embed.description = "No active conflicts or beige recovery periods."
            else:
                lines = []
                for w in wars:
                    att = await session.get(Nation, w.attacker_id)
                    dfn = await session.get(Nation, w.defender_id)
                    att_n = att.name if att else f"Nation #{w.attacker_id}"
                    dfn_n = dfn.name if dfn else f"Nation #{w.defender_id}"
                    if w.status == "active":
                        lines.append(f"• **War #{w.id}**: `{att_n}` vs `{dfn_n}` | CB: `{w.casus_belli}` | ⚡ AP: **{w.attacker_ap}** vs **{w.defender_ap}**")
                    else:
                        lines.append(f"• **War #{w.id} [BEIGE]**: `{att_n}` vs `{dfn_n}` | 🛡️ Protected until turn **{w.beige_until_turn}**")
                embed.description = "\n".join(lines)

            await ctx.respond(embed=embed)

    @war.command(name="info", description="View detailed info for a war.")
    async def war_info(
        self,
        ctx: discord.ApplicationContext,
        war_id: int = discord.Option(int, "War ID"),
    ):
        await ctx.defer()
        async with get_session() as session:
            war = await session.get(War, war_id)
            if not war:
                await ctx.respond(f"War #{war_id} not found.", ephemeral=True)
                return

            att = await session.get(Nation, war.attacker_id)
            dfn = await session.get(Nation, war.defender_id)

            embed = discord.Embed(
                title=f"⚔️ War Info #{war.id}",
                description=f"**Status:** `{war.status.upper()}` | **Casus Belli:** `{war.casus_belli}`",
                color=discord.Color.red() if war.status == "active" else discord.Color.gold(),
            )
            embed.add_field(name="Attacker", value=f"**{att.name if att else 'Unknown'}**\n⚡ AP: {war.attacker_ap}\n😓 Fatigue: {war.attacker_fatigue:.2f}", inline=True)
            embed.add_field(name="Defender", value=f"**{dfn.name if dfn else 'Unknown'}**\n⚡ AP: {war.defender_ap}\n😓 Fatigue: {war.defender_fatigue:.2f}", inline=True)
            embed.add_field(name="Theatre Environment", value=f"🌤️ Weather: `{war.weather}`\n🍂 Season: `{war.season}`", inline=False)
            await ctx.respond(embed=embed)

    @war.command(name="peace_offer", description="Propose a peace treaty with terms.")
    async def peace_offer(
        self,
        ctx: discord.ApplicationContext,
        war_id: int = discord.Option(int, "War ID"),
        reparations_per_turn: float = discord.Option(float, "Reparations money per turn", default=0.0),
        demilitarization_max_soldiers: int = discord.Option(int, "Max allowed soldiers (demilitarization cap)", default=0),
    ):
        await ctx.defer()
        async with get_session() as session:
            actor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not actor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            gs = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            current_turn = gs.turn_number if gs else 1

            try:
                demil = demilitarization_max_soldiers if demilitarization_max_soldiers > 0 else None
                treaty = await create_peace_treaty(
                    session, war_id, actor.id,
                    reparations_per_turn=reparations_per_turn,
                    demilitarization_max_soldiers=demil,
                    current_turn=current_turn,
                )
                embed = discord.Embed(
                    title="🕊️ Peace Treaty Proposed!",
                    description=f"Treaty ID **#{treaty.id}** proposed for War **#{war_id}**.",
                    color=discord.Color.blue(),
                )
                embed.add_field(name="Reparations", value=f"💰 `{treaty.reparations_per_turn:.1f}` / turn", inline=True)
                embed.add_field(name="Demilitarization", value=f"🪖 Max {treaty.demilitarization_max_soldiers or 'Unlimited'} soldiers", inline=True)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Peace offer failed: {e}", ephemeral=True)

    @war.command(name="peace_accept", description="Accept a proposed peace treaty.")
    async def peace_accept(
        self,
        ctx: discord.ApplicationContext,
        treaty_id: int = discord.Option(int, "Peace Treaty ID"),
    ):
        await ctx.defer()
        async with get_session() as session:
            actor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not actor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            gs = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            current_turn = gs.turn_number if gs else 1

            try:
                treaty = await accept_peace_treaty(session, treaty_id, actor.id, current_turn=current_turn)
                embed = discord.Embed(
                    title="🕊️ Peace Treaty Accepted!",
                    description=f"Peace Treaty **#{treaty.id}** accepted. War **#{treaty.war_id}** is now in beige protection.",
                    color=discord.Color.green(),
                )
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"⚠️ Peace accept failed: {e}", ephemeral=True)

    @war.command(name="occupation", description="View province occupations and insurgency levels.")
    async def occupation_cmd(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            actor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not actor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            stmt = select(ProvinceOccupation).where(ProvinceOccupation.occupier_nation_id == actor.id)
            occupations = (await session.execute(stmt)).scalars().all()

            embed = discord.Embed(title=f"🚩 Occupied Provinces by {actor.name}", color=discord.Color.dark_orange())
            if not occupations:
                embed.description = "Your nation currently occupies no enemy provinces."
            else:
                lines = []
                for o in occupations:
                    prov = await session.get(Province, o.province_id)
                    pname = prov.display_name if prov and prov.display_name else (prov.name if prov else f"Province #{o.province_id}")
                    lines.append(f"• **{pname}**: Progress **{o.occupation_progress:.1f}%** | Insurgency **{o.insurgency_level:.1f}%**")
                embed.description = "\n".join(lines)

            await ctx.respond(embed=embed)

    @war.command(name="map", description="View the world war-front map.")
    async def war_map(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            renderer = MapRenderer(assets_dir=ASSETS_DIR)
            res = await session.execute(select(Province).where(Province.nation_id.isnot(None)))
            provinces = res.scalars().all()
            nation_owners = {}
            if provinces:
                nation_res = await session.execute(select(Nation))
                nations = {n.id: n for n in nation_res.scalars().all()}
                for p in provinces:
                    if p.nation_id in nations:
                        hex_col = (nations[p.nation_id].color or "#00FF00").lstrip("#")
                        if len(hex_col) == 6:
                            nation_owners[p.id] = (int(hex_col[0:2], 16), int(hex_col[2:4], 16), int(hex_col[4:6], 16))

            occ_res = await session.execute(select(ProvinceOccupation))
            occupations = occ_res.scalars().all()
            occupied_provinces = {o.province_id: o.occupier_nation_id for o in occupations if o.occupation_progress > 0.0}

            img_stream = renderer.render_map(
                nation_owners=nation_owners,
                occupied_provinces=occupied_provinces,
                mode="war",
                legend_title="War Front World Map",
            )
            file = discord.File(img_stream, filename="war_front_map.png")
            embed = discord.Embed(title="⚔️ War Front World Map", color=discord.Color.dark_red())
            embed.set_image(url="attachment://war_front_map.png")
            await ctx.respond(embed=embed, file=file)

    @war.command(name="log", description="View recent combat logs for a war.")
    async def war_log_cmd(
        self,
        ctx: discord.ApplicationContext,
        war_id: int = discord.Option(int, "War ID"),
    ):
        await ctx.defer()
        async with get_session() as session:
            stmt = select(WarLog).where(WarLog.war_id == war_id).order_by(WarLog.id.desc()).limit(5)
            logs = (await session.execute(stmt)).scalars().all()

            embed = discord.Embed(title=f"📜 Recent Combat Logs: War #{war_id}", color=discord.Color.blue())
            if not logs:
                embed.description = "No combat logs recorded yet."
            else:
                for l in logs:
                    embed.add_field(
                        name=f"Turn {l.turn_number} - {l.action_type.replace('_', ' ').title()} [{l.victory_tier}]",
                        value=f"{l.summary}\n📊 Roll Diff: `{l.roll_diff:.1f}` | 🪖 Losses: `{l.casualties}`",
                        inline=False,
                    )
            await ctx.respond(embed=embed)


def _build_war_log_embed(war_log: WarLog, actor_name: str) -> discord.Embed:
    tier_colors = {
        "Immense Triumph": discord.Color.gold(),
        "Moderate Success": discord.Color.green(),
        "Pyrrhic": discord.Color.orange(),
        "Failure": discord.Color.red(),
        "Ceasefire Offered": discord.Color.blue(),
        "Ceasefire Accepted": discord.Color.purple(),
    }
    col = tier_colors.get(war_log.victory_tier, discord.Color.dark_grey())

    embed = discord.Embed(
        title=f"⚔️ War Action: {war_log.victory_tier}",
        description=f"**Actor:** {actor_name} | **Action:** `{war_log.action_type}`",
        color=col,
    )
    if war_log.province_id:
        from sylus.services.province_search import get_province_index
        prec = get_province_index().get_by_id(war_log.province_id)
        if prec:
            embed.add_field(name="Target Province", value=prec["display_name"], inline=True)
    embed.add_field(name="Roll & Scores", value=f"🎯 Roll Diff: **{war_log.roll_diff:.1f}**\nActor: `{war_log.attacker_score:.1f}` | Target: `{war_log.defender_score:.1f}`", inline=True)
    if war_log.casualties:
        embed.add_field(name="Casualties", value=f"🪖 `{war_log.casualties}`", inline=True)
    if war_log.loot_resources:
        embed.add_field(name="Looted Resources", value=f"💰 `{war_log.loot_resources}`", inline=True)
    embed.set_footer(text=f"War #{war_log.war_id} • Turn {war_log.turn_number}")
    return embed


def setup(bot: discord.Bot):
    bot.add_cog(WarCog(bot))
