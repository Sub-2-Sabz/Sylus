from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import (
    Nation,
    ResourceLedger,
    Province,
    TradeOffer,
    TradeItem,
    EscrowHold,
    PriceHistory,
    AuditLog,
    utc_now,
)
from sylus.logging import get_logger

logger = get_logger(__name__)


async def get_or_create_ledger(session: AsyncSession, nation_id: int, resource_type: str) -> ResourceLedger:
    stmt = select(ResourceLedger).where(
        ResourceLedger.nation_id == nation_id,
        ResourceLedger.resource_type == resource_type
    )
    res = await session.execute(stmt)
    ledger = res.scalar_one_or_none()
    if ledger is None:
        ledger = ResourceLedger(nation_id=nation_id, resource_type=resource_type, balance=0.0)
        session.add(ledger)
        await session.flush()
    return ledger


async def verify_and_deduct_asset(
    session: AsyncSession, nation_id: int, asset_type: str, asset_id: str, quantity: float
) -> bool:
    if quantity <= 0:
        return False
    if asset_type == "resource":
        ledger = await get_or_create_ledger(session, nation_id, asset_id)
        if ledger.balance < quantity:
            return False
        ledger.balance -= quantity
        return True
    elif asset_type == "province":
        try:
            p_id = int(asset_id)
        except ValueError:
            return False
        stmt = select(Province).where(Province.id == p_id, Province.nation_id == nation_id)
        p = (await session.execute(stmt)).scalar_one_or_none()
        if p is None:
            return False
        p.nation_id = None  # Province in escrow/limbo
        return True
    else:
        # Generic asset check (units, model_blueprint, tech_license)
        nation = await session.get(Nation, nation_id)
        return nation is not None


async def add_asset_to_nation(
    session: AsyncSession, nation_id: int, asset_type: str, asset_id: str, quantity: float
) -> None:
    if asset_type == "resource":
        ledger = await get_or_create_ledger(session, nation_id, asset_id)
        ledger.balance += quantity
    elif asset_type == "province":
        try:
            p_id = int(asset_id)
            stmt = select(Province).where(Province.id == p_id)
            p = (await session.execute(stmt)).scalar_one_or_none()
            if p:
                p.nation_id = nation_id
        except ValueError:
            pass


async def lock_in_escrow(
    session: AsyncSession,
    nation_id: int,
    asset_type: str,
    asset_id: str,
    quantity: float,
    trade_offer_id: Optional[int] = None,
    contract_id: Optional[int] = None,
) -> EscrowHold:
    success = await verify_and_deduct_asset(session, nation_id, asset_type, asset_id, quantity)
    if not success:
        raise ValueError(f"Insufficient asset/balance to lock in escrow: {asset_type}:{asset_id} x{quantity}")

    escrow = EscrowHold(
        trade_offer_id=trade_offer_id,
        contract_id=contract_id,
        nation_id=nation_id,
        asset_type=asset_type,
        asset_id=asset_id,
        quantity=quantity,
        status="locked",
    )
    session.add(escrow)
    await session.flush()
    return escrow


async def release_escrow(session: AsyncSession, escrow_hold: EscrowHold, to_nation_id: int) -> None:
    if escrow_hold.status != "locked":
        return
    await add_asset_to_nation(session, to_nation_id, escrow_hold.asset_type, escrow_hold.asset_id, escrow_hold.quantity)
    escrow_hold.status = "released"
    await session.flush()


async def refund_escrow(session: AsyncSession, escrow_hold: EscrowHold) -> None:
    if escrow_hold.status != "locked":
        return
    await add_asset_to_nation(session, escrow_hold.nation_id, escrow_hold.asset_type, escrow_hold.asset_id, escrow_hold.quantity)
    escrow_hold.status = "refunded"
    await session.flush()


async def create_direct_trade_offer(
    session: AsyncSession,
    sender_id: int,
    receiver_id: int,
    offered_items: List[Dict[str, Any]],
    requested_items: List[Dict[str, Any]],
    current_turn: int,
) -> TradeOffer:
    duration = int(config.get("trade.default_offer_duration_turns", 12))
    offer = TradeOffer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        offer_type="direct",
        status="pending",
        expires_at_turn=current_turn + duration,
        created_at_turn=current_turn,
    )
    session.add(offer)
    await session.flush()

    for item in offered_items:
        a_type, a_id, qty = item["asset_type"], str(item["asset_id"]), float(item["quantity"])
        await lock_in_escrow(session, sender_id, a_type, a_id, qty, trade_offer_id=offer.id)
        session.add(TradeItem(trade_offer_id=offer.id, side="offered", asset_type=a_type, asset_id=a_id, quantity=qty))

    for item in requested_items:
        a_type, a_id, qty = item["asset_type"], str(item["asset_id"]), float(item["quantity"])
        session.add(TradeItem(trade_offer_id=offer.id, side="requested", asset_type=a_type, asset_id=a_id, quantity=qty))

    await session.flush()
    return offer


async def accept_trade_offer(session: AsyncSession, offer_id: int, acceptor_id: int, current_turn: int) -> TradeOffer:
    offer = await session.get(TradeOffer, offer_id)
    if not offer or offer.status != "pending":
        raise ValueError("Trade offer is not pending or does not exist.")
    if offer.receiver_id and offer.receiver_id != acceptor_id:
        raise ValueError("You are not the designated recipient of this trade offer.")

    stmt_items = select(TradeItem).where(TradeItem.trade_offer_id == offer_id)
    items = (await session.execute(stmt_items)).scalars().all()
    requested_items = [i for i in items if i.side == "requested"]

    for item in requested_items:
        success = await verify_and_deduct_asset(session, acceptor_id, item.asset_type, item.asset_id, item.quantity)
        if not success:
            raise ValueError(f"Acceptor lacks required item: {item.asset_type}:{item.asset_id} x{item.quantity}")

    for item in requested_items:
        await add_asset_to_nation(session, offer.sender_id, item.asset_type, item.asset_id, item.quantity)

    stmt_escrow = select(EscrowHold).where(EscrowHold.trade_offer_id == offer_id, EscrowHold.status == "locked")
    escrows = (await session.execute(stmt_escrow)).scalars().all()
    for escrow in escrows:
        await release_escrow(session, escrow, acceptor_id)

    offer.status = "accepted"
    await session.flush()
    return offer


async def counter_trade_offer(
    session: AsyncSession,
    offer_id: int,
    counterer_id: int,
    new_offered: List[Dict[str, Any]],
    new_requested: List[Dict[str, Any]],
    current_turn: int,
) -> TradeOffer:
    original = await session.get(TradeOffer, offer_id)
    if not original or original.status != "pending":
        raise ValueError("Original offer cannot be countered.")

    stmt_escrow = select(EscrowHold).where(EscrowHold.trade_offer_id == offer_id, EscrowHold.status == "locked")
    escrows = (await session.execute(stmt_escrow)).scalars().all()
    for e in escrows:
        await refund_escrow(session, e)
    original.status = "countered"

    counter_offer = await create_direct_trade_offer(
        session,
        sender_id=counterer_id,
        receiver_id=original.sender_id,
        offered_items=new_offered,
        requested_items=new_requested,
        current_turn=current_turn,
    )
    counter_offer.original_offer_id = original.id
    await session.flush()
    return counter_offer


async def cancel_trade_offer(session: AsyncSession, offer_id: int, canceller_id: int) -> TradeOffer:
    offer = await session.get(TradeOffer, offer_id)
    if not offer or offer.status != "pending":
        raise ValueError("Offer cannot be cancelled.")
    if offer.sender_id != canceller_id:
        raise ValueError("Only the creator can cancel this offer.")

    stmt_escrow = select(EscrowHold).where(EscrowHold.trade_offer_id == offer_id, EscrowHold.status == "locked")
    escrows = (await session.execute(stmt_escrow)).scalars().all()
    for e in escrows:
        await refund_escrow(session, e)

    offer.status = "cancelled"
    await session.flush()
    return offer


async def create_market_order(
    session: AsyncSession,
    sender_id: int,
    order_type: str,
    asset_type: str,
    asset_id: str,
    total_quantity: float,
    unit_price: float,
    current_turn: int,
) -> TradeOffer:
    if total_quantity <= 0 or unit_price <= 0:
        raise ValueError("Quantity and price must be greater than zero.")

    duration = int(config.get("trade.default_offer_duration_turns", 12))
    offer = TradeOffer(
        sender_id=sender_id,
        receiver_id=None,
        offer_type=order_type,
        status="pending",
        expires_at_turn=current_turn + duration,
        created_at_turn=current_turn,
        asset_type=asset_type,
        asset_id=asset_id,
        total_quantity=total_quantity,
        filled_quantity=0.0,
        unit_price=unit_price,
    )
    session.add(offer)
    await session.flush()

    if order_type == "sell_order":
        await lock_in_escrow(session, sender_id, asset_type, asset_id, total_quantity, trade_offer_id=offer.id)
    elif order_type == "buy_order":
        total_cost = total_quantity * unit_price
        await lock_in_escrow(session, sender_id, "resource", "money", total_cost, trade_offer_id=offer.id)

    return offer


async def fill_market_order(
    session: AsyncSession, offer_id: int, filler_id: int, fill_quantity: float, current_turn: int
) -> Tuple[TradeOffer, float]:
    offer = await session.get(TradeOffer, offer_id)
    if not offer or offer.status != "pending":
        raise ValueError("Market order is not active.")
    if offer.sender_id == filler_id:
        raise ValueError("Cannot fill your own market order.")

    remaining = offer.total_quantity - offer.filled_quantity
    if fill_quantity > remaining:
        fill_quantity = remaining

    if fill_quantity <= 0:
        raise ValueError("Invalid fill quantity.")

    total_price = fill_quantity * offer.unit_price
    fee_pct = float(config.get("trade.marketplace_fee_percent", 0.02))

    if offer.offer_type == "sell_order":
        money_needed = total_price * (1.0 + fee_pct)
        success = await verify_and_deduct_asset(session, filler_id, "resource", "money", money_needed)
        if not success:
            raise ValueError(f"Insufficient money to buy asset ({money_needed:.2f} needed).")

        await add_asset_to_nation(session, offer.sender_id, "resource", "money", total_price)
        await add_asset_to_nation(session, filler_id, offer.asset_type, offer.asset_id, fill_quantity)

    elif offer.offer_type == "buy_order":
        success = await verify_and_deduct_asset(session, filler_id, offer.asset_type, offer.asset_id, fill_quantity)
        if not success:
            raise ValueError("Insufficient asset quantity to fill buy order.")

        seller_payout = total_price * (1.0 - fee_pct)
        await add_asset_to_nation(session, filler_id, "resource", "money", seller_payout)
        await add_asset_to_nation(session, offer.sender_id, offer.asset_type, offer.asset_id, fill_quantity)

    offer.filled_quantity += fill_quantity
    if offer.filled_quantity >= offer.total_quantity:
        offer.status = "fulfilled"

    ph = PriceHistory(
        asset_type=offer.asset_type,
        asset_id=offer.asset_id,
        unit_price=offer.unit_price,
        quantity=fill_quantity,
        turn_number=current_turn,
    )
    session.add(ph)

    await session.flush()
    return offer, fill_quantity


async def process_trade_turn(session: AsyncSession, current_turn: int) -> int:
    stmt = select(TradeOffer).where(TradeOffer.status == "pending", TradeOffer.expires_at_turn <= current_turn)
    expired_offers = (await session.execute(stmt)).scalars().all()
    count = 0
    for offer in expired_offers:
        stmt_escrow = select(EscrowHold).where(EscrowHold.trade_offer_id == offer.id, EscrowHold.status == "locked")
        escrows = (await session.execute(stmt_escrow)).scalars().all()
        for e in escrows:
            await refund_escrow(session, e)
        offer.status = "expired"
        count += 1
    await session.flush()
    return count
