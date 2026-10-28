import discord
from discord.ext import commands
from sqlalchemy import select
from typing import Dict, Tuple, List

from sylus.db.base import get_session_factory
from sylus.db.models import Nation, Province
from sylus.map.renderer import MapRenderer, get_cached_map_renderer
from sylus.config import config
from sylus.logging import get_logger

logger = get_logger(__name__)


class MapCog(commands.Cog):
    map_group = discord.SlashCommandGroup("map", "Map rendering and territory commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        assets_dir = config.get("map.assets_dir", "sylus/assets/world")
        self.renderer: MapRenderer = get_cached_map_renderer(assets_dir)

    @map_group.command(name="world", description="View the current world political map")
    async def world_map(self, ctx: discord.ApplicationContext):
        await ctx.defer()

        # Query nation ownership from DB
        session_factory = get_session_factory()
        async with session_factory() as session:
            nations_res = await session.execute(select(Nation))
            nations = nations_res.scalars().all()
            provinces_res = await session.execute(select(Province))
            provinces_db = provinces_res.scalars().all()

        nation_colors_by_id: Dict[int, Tuple[int, int, int]] = {}
        nation_names_by_color: Dict[Tuple[int, int, int], str] = {}
        for n in nations:
            if n.color:
                try:
                    hex_val = n.color.lstrip("#")
                    rgb = tuple(int(hex_val[i:i+2], 16) for i in (0, 2, 4))
                    if len(rgb) == 3:
                        nation_colors_by_id[n.id] = rgb
                        nation_names_by_color[rgb] = n.name
                except Exception:
                    pass

        nation_owners: Dict[int, Tuple[int, int, int]] = {}
        capitals: List[Tuple[int, int]] = []

        for p in provinces_db:
            if p.nation_id in nation_colors_by_id:
                nation_owners[p.id] = nation_colors_by_id[p.nation_id]
                if p.is_capital:
                    p_info = self.renderer.get_province(p.id)
                    if p_info and "capital_coords" in p_info:
                        capitals.append(tuple(p_info["capital_coords"]))

        img_bytes = self.renderer.render_map(
            nation_owners=nation_owners,
            capitals=capitals,
            mode="political",
            legend_title="Sylus World Map",
            nation_names=nation_names_by_color,
        )

        file = discord.File(fp=img_bytes, filename="world_map.png")
        embed = discord.Embed(
            title="🌍 Sylus Political Map",
            description=f"Total Provinces: {len(self.renderer.provinces)}",
            color=discord.Color.blue(),
        )
        embed.set_image(url="attachment://world_map.png")
        await ctx.respond(embed=embed, file=file)

    @map_group.command(name="terrain", description="View the world terrain map")
    async def terrain_map(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        img_bytes = self.renderer.render_map(mode="terrain", legend_title="Terrain Types")
        file = discord.File(fp=img_bytes, filename="terrain_map.png")
        embed = discord.Embed(
            title="🌲 Sylus Terrain Map",
            description="Overview of world terrain distributions",
            color=discord.Color.green(),
        )
        embed.set_image(url="attachment://terrain_map.png")
        await ctx.respond(embed=embed, file=file)

    @map_group.command(name="province", description="View details for a specific province")
    async def province_info(
        self,
        ctx: discord.ApplicationContext,
        province_id: discord.Option(int, "Province ID to inspect", required=True),
    ):
        await ctx.defer()
        p_info = self.renderer.get_province(province_id)
        if not p_info:
            await ctx.respond(f"❌ Province ID `{province_id}` not found.", ephemeral=True)
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            prov_db_res = await session.execute(select(Province).where(Province.id == province_id))
            prov_db = prov_db_res.scalar_one_or_none()
            owner_name = "Unclaimed"
            if prov_db and prov_db.nation_id:
                nat_res = await session.execute(select(Nation).where(Nation.id == prov_db.nation_id))
                nat = nat_res.scalar_one_or_none()
                if nat:
                    owner_name = nat.name

        adj_list = self.renderer.adjacency.get(str(province_id), [])
        adj_str = ", ".join(map(str, adj_list)) if adj_list else "None"

        embed = discord.Embed(
            title=f"🗺️ Province {province_id}: {p_info.get('name', 'Unknown')}",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Country / Region", value=str(p_info.get("country", "Unknown")), inline=True)
        embed.add_field(name="Owner Nation", value=owner_name, inline=True)
        embed.add_field(name="Terrain", value=str(p_info.get("terrain", "Unknown")).capitalize(), inline=True)
        embed.add_field(name="Climate", value=str(p_info.get("climate", "Unknown")).capitalize(), inline=True)
        embed.add_field(name="Population Capacity", value=f"{p_info.get('population_capacity', 0):,}", inline=True)
        embed.add_field(name="Adjacent Provinces", value=adj_str, inline=False)

        deposits = p_info.get("deposits", {})
        if deposits:
            dep_str = "\n".join([f"• {k.capitalize()}: {v}" for k, v in deposits.items()])
            embed.add_field(name="Resource Deposits", value=dep_str, inline=False)

        await ctx.respond(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(MapCog(bot))
