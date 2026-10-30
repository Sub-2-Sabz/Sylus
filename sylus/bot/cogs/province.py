import discord
from discord.ext import commands
from sqlalchemy import select
from typing import Optional, List

from sylus.db.base import get_session
from sylus.db.models import Province, Nation
from sylus.services.province_search import get_province_index, province_autocomplete
from sylus.logging import get_logger

logger = get_logger(__name__)

class ProvincePaginatorView(discord.ui.View):
    def __init__(self, title: str, items: List[str], user_id: int):
        super().__init__(timeout=180)
        self.title = title
        self.items = items
        self.user_id = user_id
        self.current_page = 0
        self.per_page = 10
        self.max_page = max(0, (len(items) - 1) // self.per_page) if items else 0

    def get_embed(self) -> discord.Embed:
        if not self.items:
            return discord.Embed(
                title=self.title,
                description="No matching provinces found.",
                color=discord.Color.blue()
            )

        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.items[start:end]

        embed = discord.Embed(
            title=f"{self.title} (Page {self.current_page + 1}/{self.max_page + 1})",
            description="\n".join(page_items),
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total results: {len(self.items)}")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot control this paginator.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot control this paginator.", ephemeral=True)
            return
        if self.current_page < self.max_page:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

class ProvinceCog(commands.Cog):
    """Cog for province lookup, search, and details."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.index = get_province_index()

    province_group = discord.SlashCommandGroup("province", "Province management and information")

    @province_group.command(name="info", description="View detailed information for a province")
    async def province_info(
        self,
        ctx: discord.ApplicationContext,
        province: str = discord.Option(str, "Province name, code, or ID", autocomplete=province_autocomplete)
    ):
        await ctx.defer()
        rec = self.index.resolve(province)
        if not rec:
            await ctx.respond(f"❌ Province `{province}` not found.", ephemeral=True)
            return

        pinfo = rec["raw"]
        pid = rec["id"]

        async with get_session() as session:
            stmt = select(Province).where(Province.id == pid)
            prov_db = (await session.execute(stmt)).scalar_one_or_none()

            owner_name = "Unclaimed"
            if prov_db and prov_db.nation_id:
                nat = await session.get(Nation, prov_db.nation_id)
                if nat:
                    owner_name = nat.name

        embed = discord.Embed(
            title=f"🗺️ {pinfo['display_name']}",
            color=discord.Color.gold() if owner_name != "Unclaimed" else discord.Color.light_grey()
        )
        embed.add_field(name="Code", value=f"`{rec['code']}`", inline=True)
        embed.add_field(name="Country", value=f"{rec['country']} (`{rec['country_code']}`)", inline=True)
        embed.add_field(name="Owner", value=f"**{owner_name}**", inline=True)
        embed.add_field(name="Terrain", value=pinfo.get("terrain", "plains").capitalize(), inline=True)
        embed.add_field(name="Climate", value=pinfo.get("climate", "temperate").capitalize(), inline=True)
        embed.add_field(name="Pop. Capacity", value=f"{pinfo.get('population_capacity', 100000):,}", inline=True)

        deposits = pinfo.get("deposits", {})
        dep_str = ", ".join(f"{k.capitalize()}: {v}" for k, v in deposits.items()) if deposits else "None"
        embed.add_field(name="Base Deposits", value=dep_str, inline=False)

        # Adjacency neighbors by display name
        adj_ids = self.bot.renderer.adjacency.get(str(pid), []) if hasattr(self.bot, "renderer") and self.bot.renderer else []
        neighbor_names = []
        for nid in adj_ids[:15]:
            n_rec = self.index.get_by_id(nid)
            if n_rec:
                neighbor_names.append(n_rec["display_name"])

        neighbor_str = ", ".join(neighbor_names) if neighbor_names else "None"
        embed.add_field(name="Neighbors", value=neighbor_str, inline=False)

        await ctx.respond(embed=embed)

    @province_group.command(name="search", description="Search provinces by name, alias, or country")
    async def province_search(
        self,
        ctx: discord.ApplicationContext,
        query: str = discord.Option(str, "Search text")
    ):
        await ctx.defer()
        matches = self.index.search(query, limit=100)

        lines = []
        async with get_session() as session:
            all_provs = (await session.execute(select(Province))).scalars().all()
            owner_map = {p.id: p.nation_id for p in all_provs}
            all_nats = (await session.execute(select(Nation))).scalars().all()
            nat_names = {n.id: n.name for n in all_nats}

            for m in matches:
                nid = owner_map.get(m["id"])
                owner = f"🚩 {nat_names[nid]}" if nid and nid in nat_names else "⚪ Unclaimed"
                lines.append(f"• **{m['display_name']}** (`{m['code']}`) — {m['raw'].get('terrain', 'plains')} | {owner}")

        view = ProvincePaginatorView(f"🔍 Search Results for '{query}'", lines, ctx.author.id)
        await ctx.respond(embed=view.get_embed(), view=view)

    @province_group.command(name="list", description="List all provinces in a country")
    async def province_list(
        self,
        ctx: discord.ApplicationContext,
        country: str = discord.Option(str, "Country name")
    ):
        await ctx.defer()
        matches = self.index.search(country, limit=200)
        filtered = [m for m in matches if m["country"].lower() == country.lower() or country.lower() in m["search_country"]]

        lines = []
        async with get_session() as session:
            all_provs = (await session.execute(select(Province))).scalars().all()
            owner_map = {p.id: p.nation_id for p in all_provs}
            all_nats = (await session.execute(select(Nation))).scalars().all()
            nat_names = {n.id: n.name for n in all_nats}

            for m in filtered:
                nid = owner_map.get(m["id"])
                owner = f"🚩 {nat_names[nid]}" if nid and nid in nat_names else "⚪ Unclaimed"
                lines.append(f"• **{m['display_name']}** — {m['raw'].get('terrain', 'plains')} | {owner}")

        view = ProvincePaginatorView(f"🏳️ Provinces in {country.capitalize()}", lines, ctx.author.id)
        await ctx.respond(embed=view.get_embed(), view=view)

def setup(bot: discord.Bot):
    bot.add_cog(ProvinceCog(bot))
