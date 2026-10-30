import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.base import get_session
from sylus.db.models import Nation, Province, ResourceLedger, Building, ResourceMarketIndex
from sylus.services.nation import create_nation, set_policy, build_structure, upgrade_structure, demolish_structure, claim_province
from sylus.services.province_search import get_province_index, province_autocomplete
from sylus.logging import get_logger

logger = get_logger(__name__)


class ProvincePaginatorView(discord.ui.View):
    def __init__(self, provinces_data: list, user_id: int):
        super().__init__(timeout=180)
        self.provinces_data = provinces_data
        self.user_id = user_id
        self.current_page = 0
        self.max_page = max(0, len(provinces_data) - 1)

    def get_embed(self) -> discord.Embed:
        if not self.provinces_data:
            embed = discord.Embed(
                title="Nation Provinces",
                description="No provinces owned.",
                color=discord.Color.blue(),
            )
            return embed

        data = self.provinces_data[self.current_page]
        embed = discord.Embed(
            title=f"Province: {data['name']} (ID: {data['id']})",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Terrain", value=data['terrain'].title(), inline=True)
        embed.add_field(name="Capital", value="Yes" if data['is_capital'] else "No", inline=True)
        embed.add_field(name="Population", value=f"{data['population']:,}", inline=True)
        embed.add_field(name="Infrastructure Level", value=str(data['infrastructure']), inline=True)
        embed.add_field(name="Building Slots", value=f"{data['used_slots']}/{data['slot_cap']}", inline=True)
        embed.add_field(name="Buildings", value=", ".join(data['buildings']) if data['buildings'] else "None", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_page + 1}")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return
        if self.current_page < self.max_page:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()


class NationCog(commands.Cog):
    """Cog handling nation creation, customization, policies, construction, and dashboards."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    nation = discord.SlashCommandGroup("nation", "Nation administration and economic dashboards")

    @nation.command(name="create", description="Found a new nation (one per user).")
    async def create(
        self,
        ctx: discord.ApplicationContext,
        name: str = discord.Option(str, "Name of your nation"),
        leader: str = discord.Option(str, "Name of the nation leader"),
        capital_province_id: int = discord.Option(int, "ID of your starting capital province"),
        color: str = discord.Option(str, "Hex color code e.g. #FF0000", default="#00FF00"),
        flag_url: str = discord.Option(str, "URL to flag image", default=None),
        government_type: str = discord.Option(str, "Government type", choices=["democracy", "monarchy", "republic", "junta", "communist", "theocracy"], default="republic"),
        ideology: str = discord.Option(str, "Ideology", default="centrism"),
        starting_policy: str = discord.Option(str, "Starting policy", choices=["free_market", "state_planned", "isolationism", "welfare_state"], default="free_market"),
    ):
        await ctx.defer()
        async with get_session() as session:
            try:
                nat = await create_nation(
                    session=session,
                    discord_user_id=ctx.author.id,
                    name=name,
                    leader_name=leader,
                    capital_province_id=capital_province_id,
                    color=color,
                    flag_url=flag_url,
                    government_type=government_type,
                    ideology=ideology,
                    starting_policy=starting_policy,
                )
                embed = discord.Embed(
                    title=f"Nation Founded: {nat.name}",
                    description=f"Congratulations **{leader}**! Your nation has been created.",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Government", value=nat.government_type.title(), inline=True)
                embed.add_field(name="Ideology", value=nat.ideology.title(), inline=True)
                embed.add_field(name="Capital Province ID", value=str(capital_province_id), inline=True)
                if flag_url:
                    embed.set_thumbnail(url=flag_url)
                await ctx.respond(embed=embed)
            except Exception as e:
                await ctx.respond(f"Error creating nation: {e}", ephemeral=True)

    @nation.command(name="info", description="View nation summary dashboard.")
    async def info(self, ctx: discord.ApplicationContext, user: discord.User = discord.Option(discord.User, "Target user", default=None)):
        await ctx.defer()
        target_user = user or ctx.author
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond(f"No nation found for user {target_user.mention}.", ephemeral=True)
                return

            govs_cfg = config.get("governments", {})
            gov_info = govs_cfg.get(nat.government_type, {})
            l_title = nat.custom_leader_title or gov_info.get("leader_title", "Leader")
            g_title = nat.custom_govt_title or gov_info.get("govt_title", "State")

            cap_prov = (await session.execute(select(Province).where(Province.nation_id == nat.id, Province.is_capital.is_(True)))).scalar_one_or_none()
            cap_name = cap_prov.name if cap_prov else "N/A"

            embed = discord.Embed(
                title=f"{g_title} of {nat.name}",
                color=discord.Color.from_rgb(*tuple(int(nat.color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))) if nat.color and len(nat.color)==7 else discord.Color.blue()
            )
            embed.add_field(name="Leader", value=f"{l_title} {nat.leader_name}", inline=True)
            embed.add_field(name="Capital", value=cap_name, inline=True)
            embed.add_field(name="Government", value=nat.government_type.title(), inline=True)
            embed.add_field(name="Nation Score", value=f"{nat.score:.1f}", inline=True)
            embed.add_field(name="Population", value=f"{nat.population:,}", inline=True)
            embed.add_field(name="Happiness", value=f"{nat.happiness * 100:.1f}%", inline=True)
            if nat.flag_url:
                embed.set_thumbnail(url=nat.flag_url)
            await ctx.respond(embed=embed)

    @nation.command(name="stats", description="View nation stats and score breakdown.")
    async def stats(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            provinces = (await session.execute(select(Province).where(Province.nation_id == nat.id))).scalars().all()
            buildings = (await session.execute(select(Building).where(Building.nation_id == nat.id))).scalars().all()

            embed = discord.Embed(title=f"Stats Breakdown: {nat.name}", color=discord.Color.purple())
            embed.add_field(name="Total Score", value=f"{nat.score:.2f}", inline=False)
            embed.add_field(name="Provinces Controlled", value=str(len(provinces)), inline=True)
            embed.add_field(name="Total Buildings", value=str(len(buildings)), inline=True)
            embed.add_field(name="Tax Rate", value=f"{nat.tax_rate * 100:.1f}%", inline=True)
            embed.add_field(name="Active Policies", value=", ".join(nat.active_policies.keys()) if nat.active_policies else "None", inline=False)
            await ctx.respond(embed=embed)

    @nation.command(name="economy", description="View resource ledgers and economic dashboard.")
    async def economy(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            ledgers = (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nat.id))).scalars().all()
            prices = (await session.execute(select(ResourceMarketIndex))).scalars().all()
            price_map = {p.resource_type: p.current_price for p in prices}

            embed = discord.Embed(title=f"Economic Ledger: {nat.name}", color=discord.Color.gold())
            res_lines = []
            for r in ledgers:
                p = price_map.get(r.resource_type, 1.0)
                res_lines.append(f"**{r.resource_type.title()}**: {r.balance:,.1f} (Market Price: ${p:.2f})")

            embed.description = "\n".join(res_lines) if res_lines else "No resources in ledger."
            await ctx.respond(embed=embed)

    @nation.command(name="provinces", description="Paginated dashboard of nation provinces.")
    async def provinces(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            provs = (await session.execute(select(Province).where(Province.nation_id == nat.id))).scalars().all()
            bldgs = (await session.execute(select(Building).where(Building.nation_id == nat.id))).scalars().all()

            provs_data = []
            for p in provs:
                p_bldgs = [b for b in bldgs if b.province_id == p.id]
                used_slots = sum(config.get("buildings", {}).get(b.building_type, {}).get("slot_cost", 1) for b in p_bldgs)
                b_names = [f"{b.building_type.title()} (Lvl {b.level})" for b in p_bldgs]
                provs_data.append({
                    "id": p.id,
                    "name": p.name,
                    "terrain": p.terrain,
                    "is_capital": p.is_capital,
                    "population": p.population,
                    "infrastructure": p.infrastructure,
                    "slot_cap": p.slot_cap,
                    "used_slots": used_slots,
                    "buildings": b_names,
                })

            view = ProvincePaginatorView(provs_data, ctx.author.id)
            await ctx.respond(embed=view.get_embed(), view=view)

    @nation.command(name="policy", description="Adopt or repeal a national policy.")
    async def policy(
        self,
        ctx: discord.ApplicationContext,
        action: str = discord.Option(str, "Action", choices=["adopt", "repeal"]),
        policy_name: str = discord.Option(str, "Policy name", choices=["free_market", "state_planned", "isolationism", "welfare_state"]),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                msg = await set_policy(session, nat, policy_name, enable=(action == "adopt"))
                await ctx.respond(f"✅ {msg}")
            except Exception as e:
                await ctx.respond(f"⚠️ Error: {e}", ephemeral=True)

    @nation.command(name="claim", description="Claim an unowned province adjacent to your nation.")
    async def claim(
        self,
        ctx: discord.ApplicationContext,
        province: str = discord.Option(str, "Target province to claim", autocomplete=province_autocomplete),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                prov = await claim_province(session, nat, province)
                p_disp = prov.display_name if prov.display_name else prov.name
                await ctx.respond(f"🚩 **{nat.name}** successfully claimed **{p_disp}**!")
            except Exception as e:
                await ctx.respond(f"⚠️ Claim failed: {e}", ephemeral=True)

    @nation.command(name="build", description="Construct a building in a province.")
    async def build(
        self,
        ctx: discord.ApplicationContext,
        province: str = discord.Option(str, "Target province", autocomplete=province_autocomplete),
        building_type: str = discord.Option(
            str,
            "Building type",
            choices=[
                "sawmill", "lead_mine", "iron_mine", "coal_mine", "steel_mill",
                "oil_well", "refinery", "aluminum_smelter", "munitions_factory",
                "uranium_mine", "plutonium_reactor", "research_center", "bank", "warehouse"
            ]
        ),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                b = await build_structure(session, nat, province, building_type)
                b_cfg = config.get("buildings", {}).get(building_type, {})
                rec = get_province_index().resolve(province)
                p_disp = rec["display_name"] if rec else str(province)
                await ctx.respond(f"🏗️ Construction started for **{b_cfg.get('name', building_type)}** in **{p_disp}** ({b.turns_remaining} turn(s) remaining).")
            except Exception as e:
                await ctx.respond(f"⚠️ Construction failed: {e}", ephemeral=True)

    @nation.command(name="upgrade", description="Upgrade an existing building.")
    async def upgrade(
        self,
        ctx: discord.ApplicationContext,
        building_id: int = discord.Option(int, "Building ID to upgrade"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                b = await upgrade_structure(session, nat, building_id)
                await ctx.respond(f"⬆️ Upgrading building #{building_id} to Level {b.level} ({b.turns_remaining} turn(s) remaining).")
            except Exception as e:
                await ctx.respond(f"⚠️ Upgrade failed: {e}", ephemeral=True)

    @nation.command(name="demolish", description="Demolish a building.")
    async def demolish(
        self,
        ctx: discord.ApplicationContext,
        building_id: int = discord.Option(int, "Building ID to demolish"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You do not own a nation.", ephemeral=True)
                return

            try:
                msg = await demolish_structure(session, nat, building_id)
                await ctx.respond(f"💥 {msg}")
            except Exception as e:
                await ctx.respond(f"⚠️ Demolition failed: {e}", ephemeral=True)


def setup(bot: discord.Bot):
    bot.add_cog(NationCog(bot))
