import discord
from discord.ext import commands
from sqlalchemy import select

from sylus.db.base import get_session
from sylus.db.models import Nation, TradeOffer, PriceHistory, GlobalState
from sylus.services.province_search import get_province_index, province_autocomplete
from sylus.services.trade import (
    create_direct_trade_offer,
    accept_trade_offer,
    counter_trade_offer,
    cancel_trade_offer,
    create_market_order,
    fill_market_order,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


class TradePersistentView(discord.ui.View):
    """Persistent view with fixed custom_id buttons for trade offers that survive bot restarts."""

    def __init__(self, offer_id: int = 0):
        super().__init__(timeout=None)
        self.offer_id = offer_id
        accept_cid = f"trade:accept:{offer_id}" if offer_id > 0 else "trade:accept:0"
        decline_cid = f"trade:decline:{offer_id}" if offer_id > 0 else "trade:decline:0"

        accept_btn = discord.ui.Button(label="Accept Offer", style=discord.ButtonStyle.green, custom_id=accept_cid)
        accept_btn.callback = self.accept_callback
        self.add_item(accept_btn)

        decline_btn = discord.ui.Button(label="Cancel/Decline", style=discord.ButtonStyle.red, custom_id=decline_cid)
        decline_btn.callback = self.decline_callback
        self.add_item(decline_btn)

    async def accept_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "")
        parts = custom_id.split(":")
        offer_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else self.offer_id

        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == interaction.user.id))).scalar_one_or_none()
            if not nat:
                await interaction.followup.send("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            st = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            cur_turn = st.turn_number if st else 1

            try:
                await accept_trade_offer(session, offer_id, nat.id, cur_turn)
                await session.commit()
                await interaction.followup.send(f"✅ Successfully accepted trade offer **#{offer_id}**!", ephemeral=False)
            except Exception as e:
                await interaction.followup.send(f"⚠️ Unable to accept trade: {e}", ephemeral=True)

    async def decline_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "")
        parts = custom_id.split(":")
        offer_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else self.offer_id

        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == interaction.user.id))).scalar_one_or_none()
            if not nat:
                await interaction.followup.send("You must found a nation first.", ephemeral=True)
                return

            try:
                await cancel_trade_offer(session, offer_id, nat.id)
                await session.commit()
                await interaction.followup.send(f"🚫 Trade offer **#{offer_id}** has been cancelled.", ephemeral=False)
            except Exception as e:
                await interaction.followup.send(f"⚠️ Action failed: {e}", ephemeral=True)


class TradeCog(commands.Cog):
    """Cog handling player-to-player direct trading, escrow, public marketplace, and price history."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    trade = discord.SlashCommandGroup("trade", "Direct trading, escrow, public marketplace, and market orders")

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent view handler
        self.bot.add_view(TradePersistentView())

    @trade.command(name="offer", description="Create a direct trade offer with escrow.")
    async def offer(
        self,
        ctx: discord.ApplicationContext,
        target_user: discord.User = discord.Option(discord.User, "Target nation owner"),
        offered_asset_type: str = discord.Option(str, "Asset type you offer", choices=["resource", "province", "unit", "model_blueprint", "tech_license"]),
        offered_asset_id: str = discord.Option(str, "Asset ID or resource name (e.g., money, iron, 12)"),
        offered_quantity: float = discord.Option(float, "Quantity offered"),
        requested_asset_type: str = discord.Option(str, "Asset type you request", choices=["resource", "province", "unit", "model_blueprint", "tech_license"]),
        requested_asset_id: str = discord.Option(str, "Requested asset ID or resource name"),
        requested_quantity: float = discord.Option(float, "Quantity requested"),
    ):
        await ctx.defer()
        async with get_session() as session:
            sender = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not sender:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            receiver = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not receiver:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            st = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            cur_turn = st.turn_number if st else 1

            try:
                offered = [{"asset_type": offered_asset_type, "asset_id": offered_asset_id, "quantity": offered_quantity}]
                requested = [{"asset_type": requested_asset_type, "asset_id": requested_asset_id, "quantity": requested_quantity}]

                offer_obj = await create_direct_trade_offer(session, sender.id, receiver.id, offered, requested, cur_turn)
                await session.commit()

                view = TradePersistentView(offer_obj.id)
                embed = discord.Embed(
                    title=f"🤝 Direct Trade Offer #{offer_obj.id}",
                    description=f"**{sender.name}** has proposed a trade to **{receiver.name}**.",
                    color=discord.Color.gold(),
                )
                embed.add_field(name="Offered (Locked in Escrow)", value=f"{offered_quantity} {offered_asset_type}:{offered_asset_id}", inline=True)
                embed.add_field(name="Requested", value=f"{requested_quantity} {requested_asset_type}:{requested_asset_id}", inline=True)
                embed.add_field(name="Expires At Turn", value=str(offer_obj.expires_at_turn), inline=False)

                await ctx.respond(content=target_user.mention, embed=embed, view=view)
            except Exception as e:
                await ctx.respond(f"⚠️ Unable to create trade offer: {e}", ephemeral=True)

    @trade.command(name="market_sell", description="Post a public sell order on the marketplace.")
    async def market_sell(
        self,
        ctx: discord.ApplicationContext,
        asset_type: str = discord.Option(str, "Asset type to sell", choices=["resource", "province", "unit", "model_blueprint", "tech_license"]),
        asset_id: str = discord.Option(str, "Asset ID or resource name"),
        quantity: float = discord.Option(float, "Total quantity to sell"),
        unit_price: float = discord.Option(float, "Price per unit in money ($)"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            st = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            cur_turn = st.turn_number if st else 1

            try:
                order = await create_market_order(session, nat.id, "sell_order", asset_type, asset_id, quantity, unit_price, cur_turn)
                await session.commit()
                await ctx.respond(f"📈 Posted **Sell Order #{order.id}**: {quantity}x `{asset_type}:{asset_id}` @ **${unit_price:,.2f}/unit** (Escrow locked).")
            except Exception as e:
                await ctx.respond(f"⚠️ Unable to post sell order: {e}", ephemeral=True)

    @trade.command(name="market_buy", description="Post a public buy order on the marketplace.")
    async def market_buy(
        self,
        ctx: discord.ApplicationContext,
        asset_type: str = discord.Option(str, "Asset type to buy", choices=["resource", "province", "unit", "model_blueprint", "tech_license"]),
        asset_id: str = discord.Option(str, "Asset ID, province, or resource name", autocomplete=province_autocomplete),
        quantity: float = discord.Option(float, "Total quantity to buy"),
        unit_price: float = discord.Option(float, "Offer price per unit in money ($)"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            st = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            cur_turn = st.turn_number if st else 1

            try:
                order = await create_market_order(session, nat.id, "buy_order", asset_type, asset_id, quantity, unit_price, cur_turn)
                await session.commit()
                total_money = quantity * unit_price
                await ctx.respond(f"📉 Posted **Buy Order #{order.id}**: Want {quantity}x `{asset_type}:{asset_id}` @ **${unit_price:,.2f}/unit** (Locked **${total_money:,.2f}** in escrow).")
            except Exception as e:
                await ctx.respond(f"⚠️ Unable to post buy order: {e}", ephemeral=True)

    @trade.command(name="fill", description="Fill an existing public buy or sell marketplace order.")
    async def fill(
        self,
        ctx: discord.ApplicationContext,
        order_id: int = discord.Option(int, "Marketplace Order ID"),
        quantity: float = discord.Option(float, "Quantity to fill"),
    ):
        await ctx.defer()
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            st = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            cur_turn = st.turn_number if st else 1

            try:
                order, filled_qty = await fill_market_order(session, order_id, nat.id, quantity, cur_turn)
                await session.commit()
                await ctx.respond(f"⚡ Filled **{filled_qty} units** on Market Order **#{order_id}**! Status: `{order.status}`.")
            except Exception as e:
                await ctx.respond(f"⚠️ Fill failed: {e}", ephemeral=True)

    @trade.command(name="market_list", description="List active marketplace orders.")
    async def market_list(
        self,
        ctx: discord.ApplicationContext,
        asset_type: str = discord.Option(str, "Filter asset type", choices=["all", "resource", "province", "unit", "model_blueprint", "tech_license"], default="all"),
    ):
        await ctx.defer()
        async with get_session() as session:
            stmt = select(TradeOffer).where(TradeOffer.receiver_id.is_(None), TradeOffer.status == "pending")
            if asset_type != "all":
                stmt = stmt.where(TradeOffer.asset_type == asset_type)

            orders = (await session.execute(stmt)).scalars().all()
            embed = discord.Embed(title="🛒 Sylus Public Marketplace", color=discord.Color.green())

            if not orders:
                embed.description = "No active marketplace orders match your filter."
            else:
                lines = []
                idx = get_province_index()
                for o in orders[:15]:
                    rem = o.total_quantity - o.filled_quantity
                    tag = "🔴 SELL" if o.offer_type == "sell_order" else "🟢 BUY"
                    asset_disp = o.asset_id
                    if o.asset_type == "province":
                        prec = idx.resolve(o.asset_id)
                        if prec:
                            asset_disp = prec["display_name"]
                    lines.append(f"**#{o.id}** {tag} `{o.asset_type}:{asset_disp}` - Qty: **{rem:,.1f}** @ **${o.unit_price:,.2f}**")
                embed.description = "\n".join(lines)

            await ctx.respond(embed=embed)

    @trade.command(name="price_history", description="View market price history for an asset.")
    async def price_history(
        self,
        ctx: discord.ApplicationContext,
        asset_type: str = discord.Option(str, "Asset type"),
        asset_id: str = discord.Option(str, "Asset ID or resource name"),
    ):
        await ctx.defer()
        async with get_session() as session:
            stmt = (
                select(PriceHistory)
                .where(PriceHistory.asset_type == asset_type, PriceHistory.asset_id == asset_id)
                .order_by(PriceHistory.turn_number.desc())
                .limit(10)
            )
            history = (await session.execute(stmt)).scalars().all()

            embed = discord.Embed(
                title=f"📊 Price History: {asset_type}:{asset_id}",
                color=discord.Color.purple(),
            )
            if not history:
                embed.description = "No recorded transactions for this asset."
            else:
                lines = [f"Turn **{p.turn_number}**: **${p.unit_price:,.2f}** (Volume: {p.quantity:,.1f})" for p in history]
                embed.description = "\n".join(lines)

            await ctx.respond(embed=embed)


def setup(bot: discord.Bot):
    bot.add_cog(TradeCog(bot))
