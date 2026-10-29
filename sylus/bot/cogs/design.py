import discord
from discord.ext import commands
from sqlalchemy import select

from sylus.config import config
from sylus.db.base import get_session
from sylus.db.models import Nation, GlobalState
from sylus.services.military import (
    get_military_config,
    get_category_config,
    get_component_info,
    calculate_design_stats,
    check_nation_researched_components,
    create_unit_design,
    list_nation_designs,
    get_nation_design,
    delete_nation_design,
    clone_design_for_nation,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


def get_slot_options(slot: str) -> list[tuple[str, str, str]]:
    """Returns list of (comp_key, comp_name, req_tech) for a slot."""
    mil_cfg = get_military_config()
    comps_dict = mil_cfg.get("components", {})
    target_group = slot
    if slot in ("primary_weapon", "secondary_weapon"):
        target_group = "weapons"

    group_data = comps_dict.get(target_group, {})
    options = []
    for comp_key, comp_info in group_data.items():
        name = comp_info.get("name", comp_key)
        req_tech = comp_info.get("required_tech", "")
        options.append((comp_key, name, req_tech))
    return options


def build_designer_embed(category: str, selected_components: dict) -> discord.Embed:
    cat_cfg = get_category_config(category)
    cat_name = cat_cfg.get("display_name", category.capitalize()) if cat_cfg else category
    calc = calculate_design_stats(category, selected_components)
    stats = calc["stats"]
    prod_cost = calc["production_cost"]
    upkeep = calc["upkeep"]

    embed = discord.Embed(
        title=f"🛠️ Military Unit Designer: {cat_name}",
        description=cat_cfg.get("description", "") if cat_cfg else "",
        color=discord.Color.blue(),
    )

    stats_str = (
        f"⚔️ **Attack:** {stats['attack']} | 🛡️ **Defense:** {stats['defense']}\n"
        f"💨 **Speed:** {stats['speed']} km/h | 🎯 **Range:** {stats['range']} km\n"
        f"⛽ **Fuel Use:** {stats['fuel_use']} | 👤 **Crew:** {stats['crew']}\n"
        f"🥷 **Stealth:** {stats['stealth']}% | 📡 **Detection:** {stats['detection']}%\n"
        f"🔧 **Reliability:** {int(stats['reliability'] * 100)}%"
    )
    embed.add_field(name="📊 Computed Live Stats", value=stats_str, inline=False)

    cost_parts = [f"**{k.replace('_', ' ').title()}:** {v:,.0f}" for k, v in prod_cost.items()]
    cost_str = ", ".join(cost_parts) if cost_parts else "Free"
    upkeep_parts = [f"**{k.replace('_', ' ').title()}:** {v:,.0f}" for k, v in upkeep.items()]
    upkeep_str = ", ".join(upkeep_parts) if upkeep_parts else "None"

    embed.add_field(name="💰 Production Cost & Time", value=f"{cost_str}\n⏳ **Build Time:** {calc['build_time']} turns", inline=True)
    embed.add_field(name="📉 Upkeep per Turn", value=upkeep_str, inline=True)

    sel_parts = []
    for slot, val in selected_components.items():
        if val:
            info = get_component_info(slot, val)
            comp_name = info.get("name", val) if info else val
            sel_parts.append(f"• **{slot.replace('_', ' ').title()}:** {comp_name}")

    sel_str = "\n".join(sel_parts) if sel_parts else "None (Base Configuration)"
    embed.add_field(name="🔧 Selected Components", value=sel_str, inline=False)
    embed.set_footer(text="Select components from the dropdowns below, then click Save Design.")
    return embed


class SaveDesignModal(discord.ui.Modal):
    def __init__(self, category: str, selected_components: dict):
        super().__init__(title="Save Unit Design")
        self.category = category
        self.selected_components = selected_components
        self.design_name_input = discord.ui.InputText(
            label="Model Design Name",
            placeholder="e.g. Falcon-IV, Titan-M1",
            max_length=100,
            required=True,
        )
        self.add_item(self.design_name_input)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.design_name_input.value.strip()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == interaction.user.id))).scalar_one_or_none()
            if not nat:
                await interaction.followup.send("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            is_valid, missing_techs = await check_nation_researched_components(session, nat.id, self.selected_components)
            if not is_valid:
                await interaction.followup.send(
                    f"⚠️ Your nation lacks required research tech(s) for this design: `{', '.join(missing_techs)}`",
                    ephemeral=True,
                )
                return

            try:
                design = await create_unit_design(session, nat.id, name, self.category, self.selected_components)
                await session.commit()
                embed = discord.Embed(
                    title=f"✅ Model Design Saved: {design.name}",
                    description=f"Model **#{design.id}** ({design.category}) has been added to **{nat.name}**'s blueprint library.",
                    color=discord.Color.green(),
                )
                await interaction.followup.send(embed=embed, ephemeral=False)
            except Exception as e:
                await interaction.followup.send(f"⚠️ Unable to save design: {e}", ephemeral=True)


class ComponentSelect(discord.ui.Select):
    def __init__(self, slot: str, view_parent: "DesignerWizardView"):
        self.slot = slot
        self.view_parent = view_parent
        opts = [discord.SelectOption(label="-- None / Standard --", value="none")]
        slot_comps = get_slot_options(slot)
        for comp_key, comp_name, req_tech in slot_comps[:24]:
            desc = f"Req Tech: {req_tech}" if req_tech else "Standard"
            opts.append(discord.SelectOption(label=comp_name, value=comp_key, description=desc[:100]))

        cur_val = view_parent.selected_components.get(slot, "none")
        for o in opts:
            if o.value == cur_val:
                o.default = True

        super().__init__(
            placeholder=f"Select {slot.replace('_', ' ').title()}...",
            min_values=1,
            max_values=1,
            options=opts,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == "none":
            self.view_parent.selected_components.pop(self.slot, None)
        else:
            self.view_parent.selected_components[self.slot] = selected

        embed = build_designer_embed(self.view_parent.category, self.view_parent.selected_components)
        self.view_parent.update_components_for_page()
        await interaction.response.edit_message(embed=embed, view=self.view_parent)


class CategorySelect(discord.ui.Select):
    def __init__(self, view_parent: "DesignerWizardView"):
        self.view_parent = view_parent
        cats = get_military_config().get("categories", {})
        opts = []
        for cat_key, cat_data in list(cats.items())[:25]:
            label = cat_data.get("display_name", cat_key.title())
            opts.append(discord.SelectOption(label=label, value=cat_key))

        super().__init__(placeholder="Select Unit Category...", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        self.view_parent.category = cat
        self.view_parent.selected_components = {}
        self.view_parent.current_page = 0
        self.view_parent.update_components_for_page()
        embed = build_designer_embed(cat, self.view_parent.selected_components)
        await interaction.response.edit_message(embed=embed, view=self.view_parent)


class DesignerWizardView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.category: str = "fighters"
        self.selected_components: dict = {}
        self.current_page: int = 0
        self.update_components_for_page()

    def update_components_for_page(self):
        self.clear_items()
        cat_cfg = get_category_config(self.category)
        allowed_slots = cat_cfg.get("allowed_component_slots", []) if cat_cfg else []

        # Category select menu
        self.add_item(CategorySelect(self))

        # Paginate slots (up to 3 per page so action rows <= 5)
        page_size = 3
        total_pages = max(1, (len(allowed_slots) + page_size - 1) // page_size)
        if self.current_page >= total_pages:
            self.current_page = 0

        start_idx = self.current_page * page_size
        page_slots = allowed_slots[start_idx : start_idx + page_size]

        for slot in page_slots:
            self.add_item(ComponentSelect(slot, self))

        # Page buttons + Save button row
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            prev_btn.callback = self.prev_page_callback
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(
                label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1)
            )
            next_btn.callback = self.next_page_callback
            self.add_item(next_btn)

        save_btn = discord.ui.Button(label="💾 Save Model", style=discord.ButtonStyle.success)
        save_btn.callback = self.save_callback
        self.add_item(save_btn)

    async def prev_page_callback(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
        self.update_components_for_page()
        embed = build_designer_embed(self.category, self.selected_components)
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page_callback(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_components_for_page()
        embed = build_designer_embed(self.category, self.selected_components)
        await interaction.response.edit_message(embed=embed, view=self)

    async def save_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the command author can save this design.", ephemeral=True)
            return
        modal = SaveDesignModal(self.category, self.selected_components)
        await interaction.response.send_modal(modal)


class DesignCog(commands.Cog):
    """Cog handling military unit designer UI, saved models, and blueprint licensing."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    design = discord.SlashCommandGroup("design", "Military unit designer, model library, and blueprint licensing")

    @design.command(name="create", description="Open the interactive multi-step military unit designer UI.")
    async def create(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

        view = DesignerWizardView(ctx.author.id)
        embed = build_designer_embed("fighters", {})
        await ctx.respond(embed=embed, view=view)

    @design.command(name="list", description="List saved unit model designs owned by your nation.")
    async def list_models(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            designs = await list_nation_designs(session, nat.id)
            embed = discord.Embed(
                title=f"📐 Unit Models Blueprint Library: {nat.name}",
                color=discord.Color.blue(),
            )
            if not designs:
                embed.description = "No unit models saved yet. Create one with `/design create`!"
            else:
                lines = []
                for d in designs:
                    atk = d.stats.get("attack", 0)
                    dfn = d.stats.get("defense", 0)
                    lines.append(f"**#{d.id}** `{d.name}` ({d.category.title()}) — Atk: **{atk}** | Def: **{dfn}** | Build Time: **{d.build_time}t**")
                embed.description = "\n".join(lines)

            await ctx.respond(embed=embed)

    @design.command(name="info", description="View detailed stats and component breakdown of a model design.")
    async def info_model(
        self,
        ctx: discord.ApplicationContext,
        design_id: int = discord.Option(int, "Model Design ID"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            d = await get_nation_design(session, nat.id, design_id)
            if not d:
                await ctx.respond(f"Model design #{design_id} not found in your nation's library.", ephemeral=True)
                return

            embed = build_designer_embed(d.category, d.components)
            embed.title = f"🔍 Model #{d.id}: {d.name}"
            await ctx.respond(embed=embed)

    @design.command(name="delete", description="Delete a model design from your nation's blueprint library.")
    async def delete_model(
        self,
        ctx: discord.ApplicationContext,
        design_id: int = discord.Option(int, "Model Design ID to delete"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            success = await delete_nation_design(session, nat.id, design_id)
            if success:
                await ctx.respond(f"🗑️ Successfully deleted model design **#{design_id}**.")
            else:
                await ctx.respond(f"⚠️ Unable to delete design #{design_id}. Ensure you own it.", ephemeral=True)

    @design.command(name="license", description="License a model design blueprint directly to another nation.")
    async def license_model(
        self,
        ctx: discord.ApplicationContext,
        design_id: int = discord.Option(int, "Model Design ID to license"),
        target_user: discord.User = discord.Option(discord.User, "Target nation leader"),
        fee: float = discord.Option(float, "License fee in money ($)", default=0.0),
    ):
        await ctx.defer()
        async with get_session() as session:
            licensor = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not licensor:
                await ctx.respond("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            licensee = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not licensee:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            d = await get_nation_design(session, licensor.id, design_id)
            if not d:
                await ctx.respond(f"Model design #{design_id} not found in your library.", ephemeral=True)
                return

            if fee > 0:
                # Deduct fee from licensee and add to licensor
                from sylus.services.trade import verify_and_deduct_asset, add_asset_to_nation
                deducted = await verify_and_deduct_asset(session, licensee.id, "resource", "money", fee)
                if not deducted:
                    await ctx.respond(f"⚠️ Target nation {licensee.name} lacks ${fee:,.2f} for license fee.", ephemeral=True)
                    return
                await add_asset_to_nation(session, licensor.id, "resource", "money", fee)

            cloned = await clone_design_for_nation(session, d.id, licensee.id, custom_name=f"{d.name} (Licensed)")
            await session.commit()

            embed = discord.Embed(
                title="📜 Blueprint License Granted",
                description=f"**{licensor.name}** has licensed blueprint **{d.name}** to **{licensee.name}**!",
                color=discord.Color.gold(),
            )
            embed.add_field(name="New Model ID", value=f"#{cloned.id}", inline=True)
            embed.add_field(name="License Fee", value=f"${fee:,.2f}", inline=True)
            await ctx.respond(content=target_user.mention, embed=embed)


def setup(bot: discord.Bot):
    bot.add_cog(DesignCog(bot))
