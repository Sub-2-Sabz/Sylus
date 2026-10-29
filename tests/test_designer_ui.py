import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from sylus.db.models import Nation, UnitDesign, NationTech, ResourceLedger, TradeOffer, EscrowHold
from sylus.services.military import (
    create_unit_design,
    list_nation_designs,
    get_nation_design,
    delete_nation_design,
    clone_design_for_nation,
    calculate_design_stats,
    check_nation_researched_components,
)
from sylus.services.trade import (
    create_direct_trade_offer,
    accept_trade_offer,
    create_market_order,
    fill_market_order,
    get_or_create_ledger,
)
from sylus.bot.cogs.design import build_designer_embed, get_slot_options


@pytest.mark.asyncio
async def test_military_design_lifecycle(db_session: AsyncSession):
    # Create test nation
    nation = Nation(name="Valyria", discord_user_id=111222, leader_name="Aegon")
    db_session.add(nation)
    await db_session.commit()
    await db_session.refresh(nation)

    # Unlock required techs
    db_session.add(NationTech(nation_id=nation.id, tech_id="mil_aesthetics_aviation"))
    await db_session.commit()

    components = {
        "chassis": "light_chassis",
        "engine": "turbojet_engine",
        "primary_weapon": "air_superiority_cannon",
    }

    # Unlock basic infantry for chassis
    db_session.add(NationTech(nation_id=nation.id, tech_id="mil_basic_infantry"))
    await db_session.commit()

    # Create design
    design = await create_unit_design(db_session, nation.id, "Skyhawk-V1", "fighters", components)
    assert design.id is not None
    assert design.name == "Skyhawk-V1"
    assert design.category == "fighters"

    # List designs
    designs = await list_nation_designs(db_session, nation.id)
    assert len(designs) == 1
    assert designs[0].id == design.id

    # Get design
    fetched = await get_nation_design(db_session, nation.id, design.id)
    assert fetched is not None
    assert fetched.name == "Skyhawk-V1"

    # Test embed helper
    embed = build_designer_embed("fighters", components)
    assert "Skyhawk" not in embed.title  # Embed title is generic category title
    assert len(embed.fields) >= 3

    # Clone design for another nation
    nation2 = Nation(name="Sparta", discord_user_id=333444, leader_name="Leonidas")
    db_session.add(nation2)
    await db_session.commit()

    cloned = await clone_design_for_nation(db_session, design.id, nation2.id, custom_name="Skyhawk-Sparta")
    assert cloned.id != design.id
    assert cloned.nation_id == nation2.id
    assert cloned.name == "Skyhawk-Sparta"

    # Delete design
    success = await delete_nation_design(db_session, nation.id, design.id)
    assert success is True

    fetched_after = await get_nation_design(db_session, nation.id, design.id)
    assert fetched_after is None


@pytest.mark.asyncio
async def test_model_blueprint_trade_and_escrow(db_session: AsyncSession):
    # Create seller and buyer
    seller = Nation(name="SellerNation", discord_user_id=555666, leader_name="Seller")
    buyer = Nation(name="BuyerNation", discord_user_id=777888, leader_name="Buyer")
    db_session.add_all([seller, buyer])
    await db_session.commit()

    # Buyer starting money
    buyer_ledger = await get_or_create_ledger(db_session, buyer.id, "money")
    buyer_ledger.balance = 50000.0

    # Unlock tech for seller and create design
    db_session.add_all([
        NationTech(nation_id=seller.id, tech_id="mil_basic_infantry"),
        NationTech(nation_id=seller.id, tech_id="mil_aesthetics_aviation"),
    ])
    await db_session.commit()

    design = await create_unit_design(
        db_session,
        seller.id,
        "Viper-Interception",
        "fighters",
        {"chassis": "light_chassis", "engine": "turbojet_engine"},
    )

    # Post marketplace sell order for model_blueprint
    order = await create_market_order(
        db_session,
        sender_id=seller.id,
        order_type="sell_order",
        asset_type="model_blueprint",
        asset_id=str(design.id),
        total_quantity=1.0,
        unit_price=10000.0,
        current_turn=1,
    )
    assert order.id is not None

    # Verify escrow hold exists
    escrow_stmt = select(EscrowHold).where(EscrowHold.trade_offer_id == order.id)
    escrows = (await db_session.execute(escrow_stmt)).scalars().all()
    assert len(escrows) == 1
    assert escrows[0].asset_type == "model_blueprint"
    assert escrows[0].asset_id == str(design.id)

    # Buyer fills market order
    filled_order, filled_qty = await fill_market_order(
        db_session,
        offer_id=order.id,
        filler_id=buyer.id,
        fill_quantity=1.0,
        current_turn=1,
    )
    assert filled_qty == 1.0
    assert filled_order.status == "fulfilled"

    # Buyer should now have a cloned blueprint model in their library
    buyer_designs = await list_nation_designs(db_session, buyer.id)
    assert len(buyer_designs) == 1
    assert "Viper-Interception" in buyer_designs[0].name


def test_slot_options_loader():
    opts = get_slot_options("chassis")
    assert len(opts) > 0
    assert any(o[0] == "light_chassis" for o in opts)

    weapon_opts = get_slot_options("primary_weapon")
    assert len(weapon_opts) > 0
    assert any(o[0] == "assault_rifles" for o in weapon_opts)
