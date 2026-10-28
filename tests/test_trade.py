import pytest
from sqlalchemy import select

from sylus.db.models import Nation, ResourceLedger, TradeOffer, EscrowHold, PriceHistory
from sylus.services.trade import (
    get_or_create_ledger,
    lock_in_escrow,
    refund_escrow,
    create_direct_trade_offer,
    accept_trade_offer,
    cancel_trade_offer,
    counter_trade_offer,
    create_market_order,
    fill_market_order,
    process_trade_turn,
)


@pytest.mark.asyncio
async def test_escrow_locking_and_negative_balance_prevention(db_session):
    nat = Nation(name="Nation Alpha", discord_user_id=1001)
    db_session.add(nat)
    await db_session.commit()

    ledger = await get_or_create_ledger(db_session, nat.id, "wood")
    ledger.balance = 50.0
    await db_session.commit()

    # Attempt to lock 100 wood (exceeds balance of 50)
    with pytest.raises(ValueError, match="Insufficient asset/balance"):
        await lock_in_escrow(db_session, nat.id, "resource", "wood", 100.0)

    # Balance must remain non-negative and untouched (50.0)
    await db_session.refresh(ledger)
    assert ledger.balance == 50.0

    # Lock valid 30 wood in escrow
    escrow = await lock_in_escrow(db_session, nat.id, "resource", "wood", 30.0)
    await db_session.refresh(ledger)
    assert ledger.balance == 20.0
    assert escrow.status == "locked"

    # Refund escrow
    await refund_escrow(db_session, escrow)
    await db_session.refresh(ledger)
    assert ledger.balance == 50.0
    assert escrow.status == "refunded"


@pytest.mark.asyncio
async def test_direct_trade_offer_and_acceptance(db_session):
    nat_a = Nation(name="Senderland", discord_user_id=2001)
    nat_b = Nation(name="Receiverland", discord_user_id=2002)
    db_session.add_all([nat_a, nat_b])
    await db_session.commit()

    # Give A 100 wood, give B $500 money
    ledger_a_wood = await get_or_create_ledger(db_session, nat_a.id, "wood")
    ledger_a_wood.balance = 100.0

    ledger_b_money = await get_or_create_ledger(db_session, nat_b.id, "money")
    ledger_b_money.balance = 500.0
    await db_session.commit()

    # A offers 40 wood for $200 money from B
    offered = [{"asset_type": "resource", "asset_id": "wood", "quantity": 40.0}]
    requested = [{"asset_type": "resource", "asset_id": "money", "quantity": 200.0}]

    offer = await create_direct_trade_offer(db_session, nat_a.id, nat_b.id, offered, requested, current_turn=1)
    await db_session.commit()

    # Wood locked in escrow from A
    await db_session.refresh(ledger_a_wood)
    assert ledger_a_wood.balance == 60.0
    assert offer.status == "pending"

    # B accepts offer
    await accept_trade_offer(db_session, offer.id, nat_b.id, current_turn=1)
    await db_session.commit()

    # Verify balances: A gets $200 money, B gets 40 wood
    ledger_a_money = await get_or_create_ledger(db_session, nat_a.id, "money")
    ledger_b_wood = await get_or_create_ledger(db_session, nat_b.id, "wood")

    assert ledger_a_money.balance == 200.0
    assert ledger_b_money.balance == 300.0
    assert ledger_b_wood.balance == 40.0
    assert offer.status == "accepted"


@pytest.mark.asyncio
async def test_trade_offer_cancellation(db_session):
    nat_a = Nation(name="CancellerNation", discord_user_id=3001)
    nat_b = Nation(name="OtherNation", discord_user_id=3002)
    db_session.add_all([nat_a, nat_b])
    await db_session.commit()

    ledger = await get_or_create_ledger(db_session, nat_a.id, "iron")
    ledger.balance = 100.0
    await db_session.commit()

    offered = [{"asset_type": "resource", "asset_id": "iron", "quantity": 50.0}]
    requested = [{"asset_type": "resource", "asset_id": "money", "quantity": 100.0}]

    offer = await create_direct_trade_offer(db_session, nat_a.id, nat_b.id, offered, requested, current_turn=1)
    await db_session.commit()

    assert ledger.balance == 50.0

    # Cancel offer
    await cancel_trade_offer(db_session, offer.id, nat_a.id)
    await db_session.commit()

    await db_session.refresh(ledger)
    assert ledger.balance == 100.0
    assert offer.status == "cancelled"


@pytest.mark.asyncio
async def test_counter_trade_offer(db_session):
    nat_a = Nation(name="Party A", discord_user_id=4001)
    nat_b = Nation(name="Party B", discord_user_id=4002)
    db_session.add_all([nat_a, nat_b])
    await db_session.commit()

    ledger_a = await get_or_create_ledger(db_session, nat_a.id, "wood")
    ledger_a.balance = 100.0
    ledger_b = await get_or_create_ledger(db_session, nat_b.id, "iron")
    ledger_b.balance = 50.0
    await db_session.commit()

    # Original offer: A offers 50 wood for 20 iron from B
    offered = [{"asset_type": "resource", "asset_id": "wood", "quantity": 50.0}]
    requested = [{"asset_type": "resource", "asset_id": "iron", "quantity": 20.0}]
    offer = await create_direct_trade_offer(db_session, nat_a.id, nat_b.id, offered, requested, current_turn=1)
    await db_session.commit()

    assert ledger_a.balance == 50.0

    # B counters: B offers 15 iron for 40 wood
    counter_offered = [{"asset_type": "resource", "asset_id": "iron", "quantity": 15.0}]
    counter_requested = [{"asset_type": "resource", "asset_id": "wood", "quantity": 40.0}]

    counter_offer = await counter_trade_offer(
        db_session, offer.id, nat_b.id, counter_offered, counter_requested, current_turn=1
    )
    await db_session.commit()

    # Original offer cancelled, A's 50 wood refunded
    await db_session.refresh(ledger_a)
    assert ledger_a.balance == 100.0
    assert offer.status == "countered"

    # B's 15 iron locked in escrow for counter offer
    await db_session.refresh(ledger_b)
    assert ledger_b.balance == 35.0
    assert counter_offer.status == "pending"


@pytest.mark.asyncio
async def test_marketplace_buy_and_sell_orders_with_partial_fills(db_session):
    seller = Nation(name="Merchant Nation", discord_user_id=5001)
    buyer = Nation(name="Buyer Nation", discord_user_id=5002)
    db_session.add_all([seller, buyer])
    await db_session.commit()

    # Seller has 100 steel; Buyer has $1000 money
    l_steel = await get_or_create_ledger(db_session, seller.id, "steel")
    l_steel.balance = 100.0
    l_money_b = await get_or_create_ledger(db_session, buyer.id, "money")
    l_money_b.balance = 1000.0
    await db_session.commit()

    # Seller posts sell order: 100 steel @ $5.00/unit
    order = await create_market_order(db_session, seller.id, "sell_order", "resource", "steel", 100.0, 5.0, current_turn=1)
    await db_session.commit()

    assert l_steel.balance == 0.0

    # Buyer fills 40 steel
    _, fill1 = await fill_market_order(db_session, order.id, buyer.id, 40.0, current_turn=1)
    await db_session.commit()

    assert fill1 == 40.0
    assert order.filled_quantity == 40.0
    assert order.status == "pending"

    # Check buyer steel & seller money
    l_steel_b = await get_or_create_ledger(db_session, buyer.id, "steel")
    l_money_s = await get_or_create_ledger(db_session, seller.id, "money")
    assert l_steel_b.balance == 40.0
    assert l_money_s.balance == 200.0  # 40 * $5.00

    # Fill remaining 60 steel
    _, fill2 = await fill_market_order(db_session, order.id, buyer.id, 60.0, current_turn=1)
    await db_session.commit()

    assert fill2 == 60.0
    assert order.filled_quantity == 100.0
    assert order.status == "fulfilled"


@pytest.mark.asyncio
async def test_marketplace_order_expiry(db_session):
    nat = Nation(name="Trader", discord_user_id=6001)
    db_session.add(nat)
    await db_session.commit()

    ledger = await get_or_create_ledger(db_session, nat.id, "oil")
    ledger.balance = 50.0
    await db_session.commit()

    # Create sell order expiring at turn 13
    order = await create_market_order(db_session, nat.id, "sell_order", "resource", "oil", 50.0, 10.0, current_turn=1)
    await db_session.commit()

    assert ledger.balance == 0.0

    # Process turn 13
    expired_count = await process_trade_turn(db_session, current_turn=13)
    await db_session.commit()

    assert expired_count == 1
    assert order.status == "expired"

    await db_session.refresh(ledger)
    assert ledger.balance == 50.0
