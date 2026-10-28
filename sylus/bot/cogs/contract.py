import discord
from discord.ext import commands
from sqlalchemy import select

from sylus.db.base import get_session
from sylus.db.models import Nation, Contract, ContractSignatory, GlobalState
from sylus.services.contract import (
    create_contract,
    sign_contract,
    file_appeal,
    admin_resolve_appeal,
    get_or_create_reputation,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


class ContractSignView(discord.ui.View):
    """Persistent view with fixed custom_id buttons for signing contracts that survive bot restarts."""

    def __init__(self, contract_id: int = 0):
        super().__init__(timeout=None)
        self.contract_id = contract_id
        sign_cid = f"contract:sign:{contract_id}" if contract_id > 0 else "contract:sign:0"
        reject_cid = f"contract:reject:{contract_id}" if contract_id > 0 else "contract:reject:0"

        sign_btn = discord.ui.Button(label="Sign Contract", style=discord.ButtonStyle.green, custom_id=sign_cid)
        sign_btn.callback = self.sign_callback
        self.add_item(sign_btn)

        reject_btn = discord.ui.Button(label="Reject Contract", style=discord.ButtonStyle.red, custom_id=reject_cid)
        reject_btn.callback = self.reject_callback
        self.add_item(reject_btn)

    async def sign_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "")
        parts = custom_id.split(":")
        contract_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else self.contract_id

        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == interaction.user.id))).scalar_one_or_none()
            if not nat:
                await interaction.followup.send("You must found a nation first with `/nation create`.", ephemeral=True)
                return

            st = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
            cur_turn = st.turn_number if st else 1

            try:
                c = await sign_contract(session, contract_id, nat.id, cur_turn)
                await session.commit()
                status_msg = "🖊️ Signed! Contract is now **ACTIVE & IMMUTABLE**." if c.status == "active" else "🖊️ Signed! Awaiting remaining signatures."
                await interaction.followup.send(f"✅ {status_msg}", ephemeral=False)
            except Exception as e:
                await interaction.followup.send(f"⚠️ Unable to sign contract: {e}", ephemeral=True)

    async def reject_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "")
        parts = custom_id.split(":")
        contract_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else self.contract_id

        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == interaction.user.id))).scalar_one_or_none()
            if not nat:
                await interaction.followup.send("You must found a nation first.", ephemeral=True)
                return

            c = await session.get(Contract, contract_id)
            if c and c.status == "pending_signatures":
                c.status = "admin_cancelled"
                await session.commit()
                await interaction.followup.send(f"❌ Contract **#{contract_id}** rejected and cancelled.", ephemeral=False)
            else:
                await interaction.followup.send("⚠️ Contract is not pending.", ephemeral=True)


class ContractCog(commands.Cog):
    """Cog handling official contracts, automated turn enforcement, appeals, and nation reputation."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    contract = discord.SlashCommandGroup("contract", "Contracts, obligations, appeals, and nation reputation")

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent view handler
        self.bot.add_view(ContractSignView())

    @contract.command(name="create", description="Propose a formal contract to another nation.")
    async def create(
        self,
        ctx: discord.ApplicationContext,
        title: str = discord.Option(str, "Contract Title"),
        contract_type: str = discord.Option(
            str,
            "Type of contract",
            choices=[
                "trade_agreement",
                "non_aggression_pact",
                "defense_pact",
                "alliance",
                "military_aid",
                "loan_debt",
                "tech_sharing",
                "resource_supply",
                "tribute_vassalage",
                "peace_treaty",
                "custom",
            ],
        ),
        target_user: discord.User = discord.Option(discord.User, "Counterparty nation owner"),
        duration_turns: int = discord.Option(int, "Contract duration in turns", default=24),
        penalty_type: str = discord.Option(
            str,
            "Stated breach penalty",
            choices=["fine", "asset_seizure", "tariff", "sanction", "temporary_ban", "permanent_ban"],
            default="fine",
        ),
        recurring_asset_type: str = discord.Option(str, "Asset type for recurring payment/obligation", default="resource"),
        recurring_asset_id: str = discord.Option(str, "Asset ID or resource name (e.g. money, wood)", default="money"),
        recurring_amount: float = discord.Option(float, "Recurring amount paid each turn by target party", default=0.0),
    ):
        await ctx.defer()
        async with get_session() as session:
            party_a = (await session.execute(select(Nation).where(Nation.discord_user_id == ctx.author.id))).scalar_one_or_none()
            if not party_a:
                await ctx.respond("You must found a nation first.", ephemeral=True)
                return

            party_b = (await session.execute(select(Nation).where(Nation.discord_user_id == target_user.id))).scalar_one_or_none()
            if not party_b:
                await ctx.respond(f"Target user {target_user.mention} does not own a nation.", ephemeral=True)
                return

            obligations = []
            if recurring_amount > 0:
                obligations.append({
                    "payer_id": party_b.id,
                    "payee_id": party_a.id,
                    "obligation_type": "recurring_per_turn",
                    "asset_type": recurring_asset_type,
                    "asset_id": recurring_asset_id,
                    "amount": recurring_amount,
                })

            try:
                c = await create_contract(
                    session,
                    title=title,
                    contract_type=contract_type,
                    party_a_id=party_a.id,
                    party_b_id=party_b.id,
                    duration_turns=duration_turns,
                    obligations_data=obligations,
                    penalty_type=penalty_type,
                )
                await session.commit()

                view = ContractSignView(c.id)
                embed = discord.Embed(
                    title=f"📜 Contract Proposal #{c.id}: {title}",
                    description=c.plain_language_summary,
                    color=discord.Color.gold(),
                )
                embed.set_footer(text="Both parties must sign using persistent buttons below.")

                await ctx.respond(content=target_user.mention, embed=embed, view=view)
            except Exception as e:
                await ctx.respond(f"⚠️ Unable to create contract: {e}", ephemeral=True)

    @contract.command(name="info", description="View contract summary and status.")
    async def info(self, ctx: discord.ApplicationContext, contract_id: int = discord.Option(int, "Contract ID")):
        await ctx.defer()
        async with get_session() as session:
            c = await session.get(Contract, contract_id)
            if not c:
                await ctx.respond("Contract not found.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"📜 Contract #{c.id}: {c.title}",
                description=c.plain_language_summary,
                color=discord.Color.green() if c.status == "active" else discord.Color.red() if c.status in ("breached", "enforced") else discord.Color.blue(),
            )
            embed.add_field(name="Status", value=f"`{c.status.upper()}`", inline=True)
            embed.add_field(name="Immutable", value=str(c.is_immutable), inline=True)
            embed.add_field(name="Duration", value=f"{c.duration_turns} turns (Start: {c.start_turn}, End: {c.end_turn})", inline=False)

            await ctx.respond(embed=embed)

    @contract.command(name="appeal", description="File an appeal for a breached contract within appeal window.")
    async def appeal(
        self,
        ctx: discord.ApplicationContext,
        contract_id: int = discord.Option(int, "Contract ID"),
        reason: str = discord.Option(str, "Reason for appeal"),
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
                app = await file_appeal(session, contract_id, nat.id, reason, cur_turn)
                await session.commit()
                await ctx.respond(f"⚖️ Appeal **#{app.id}** submitted for Contract **#{contract_id}**. Contract is now under arbitration review.")
            except Exception as e:
                await ctx.respond(f"⚠️ Appeal failed: {e}", ephemeral=True)

    @contract.command(name="reputation", description="View nation contract fulfillment reputation score.")
    async def reputation(
        self,
        ctx: discord.ApplicationContext,
        target_user: discord.User = discord.Option(discord.User, "Target nation owner", default=None),
    ):
        await ctx.defer()
        user = target_user or ctx.author
        async with get_session() as session:
            nat = (await session.execute(select(Nation).where(Nation.discord_user_id == user.id))).scalar_one_or_none()
            if not nat:
                await ctx.respond("Nation not found.", ephemeral=True)
                return

            rep = await get_or_create_reputation(session, nat.id)
            embed = discord.Embed(
                title=f"⭐ Reputation Score: {nat.name}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Reputation Score", value=f"**{rep.score:.1f} / 200.0**", inline=False)
            embed.add_field(name="Contracts Fulfilled", value=str(rep.contracts_fulfilled), inline=True)
            embed.add_field(name="Contracts Breached", value=str(rep.contracts_breached), inline=True)

            await ctx.respond(embed=embed)


def setup(bot: discord.Bot):
    bot.add_cog(ContractCog(bot))
