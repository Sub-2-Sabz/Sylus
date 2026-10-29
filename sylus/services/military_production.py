import math
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import (
    Nation, Province, Building, ResourceLedger, UnitDesign,
    MilitaryQueue, MilitaryFormation, SpyIntel, utc_now
)
from sylus.logging import get_logger

logger = get_logger(__name__)

CATEGORY_FACILITY_MAP = {
    "infantry": "factory",
    "air_defense": "factory",
    "tanks": "factory",
    "apcs": "factory",
    "artillery": "factory",
    "missiles": "factory",
    "nuclear_delivery": "factory",
    "warships": "shipyard",
    "submarines": "shipyard",
    "fighters": "airbase",
    "bombers": "airbase",
    "helicopters": "airbase",
    "drones": "airbase",
}


def get_facility_type_for_category(category: str) -> str:
    return CATEGORY_FACILITY_MAP.get(category, "factory")


async def get_province_facility_capacity(session: AsyncSession, province_id: int, facility_type: str) -> int:
    stmt = select(Building).where(Building.province_id == province_id, Building.turns_remaining == 0)
    res = await session.execute(stmt)
    buildings = res.scalars().all()
    b_config = config.get("buildings", {})

    total_capacity = 0
    for b in buildings:
        b_info = b_config.get(b.building_type, {})
        if b_info.get("facility_type") == facility_type:
            total_capacity += b_info.get("production_capacity", 0) * b.level
    return total_capacity


async def get_province_queued_units_count(session: AsyncSession, province_id: int, facility_type: str) -> int:
    stmt = select(func.sum(MilitaryQueue.quantity)).where(
        MilitaryQueue.province_id == province_id,
        MilitaryQueue.facility_type == facility_type
    )
    res = await session.execute(stmt)
    val = res.scalar()
    return int(val) if val else 0


async def recruit_manpower(session: AsyncSession, nation_id: int, quantity: int) -> Nation:
    if quantity <= 0:
        raise ValueError("Quantity must be positive.")

    nation = await session.get(Nation, nation_id)
    if not nation:
        raise ValueError(f"Nation #{nation_id} not found.")

    if nation.unemployed < quantity:
        raise ValueError(f"Insufficient unemployed population ({nation.unemployed} available).")

    logistics_cfg = config.get("military", {}).get("logistics", {})
    total_cost = float(logistics_cfg.get("manpower_recruit_cost_money", 10)) * quantity

    stmt = select(ResourceLedger).where(
        ResourceLedger.nation_id == nation_id, ResourceLedger.resource_type == "money"
    )
    res = await session.execute(stmt)
    money_ledger = res.scalar_one_or_none()
    money_bal = money_ledger.balance if money_ledger else 0.0

    if money_bal < total_cost:
        raise ValueError(f"Insufficient money ({money_bal:.2f} available, {total_cost:.2f} required).")

    money_ledger.balance -= total_cost
    nation.unemployed -= quantity
    nation.soldiers += quantity

    await session.commit()
    logger.info("Recruited manpower", nation_id=nation_id, quantity=quantity)
    return nation


async def enqueue_military_production(
    session: AsyncSession, nation_id: int, province_id: int, design_id: int, quantity: int = 1
) -> MilitaryQueue:
    if quantity <= 0:
        raise ValueError("Quantity must be positive.")

    province = await session.get(Province, province_id)
    if not province or province.nation_id != nation_id:
        raise ValueError(f"Province #{province_id} does not belong to nation #{nation_id}.")

    design = await session.get(UnitDesign, design_id)
    if not design or design.nation_id != nation_id:
        raise ValueError(f"Unit design #{design_id} not found or not owned.")

    facility_type = get_facility_type_for_category(design.category)
    capacity = await get_province_facility_capacity(session, province_id, facility_type)
    currently_queued = await get_province_queued_units_count(session, province_id, facility_type)

    if currently_queued + quantity > capacity:
        raise ValueError(
            f"Province facility '{facility_type}' capacity limit reached ({currently_queued}/{capacity})."
        )

    prod_cost = design.production_cost or {}
    total_costs = {res: float(amt) * quantity for res, amt in prod_cost.items()}

    stmt = select(ResourceLedger).where(ResourceLedger.nation_id == nation_id)
    res = await session.execute(stmt)
    ledgers = {r.resource_type: r for r in res.scalars().all()}

    for res_type, req_amount in total_costs.items():
        ledger = ledgers.get(res_type)
        available = ledger.balance if ledger else 0.0
        if available < req_amount:
            raise ValueError(f"Insufficient {res_type} ({available:.2f} available, {req_amount:.2f} required).")

    for res_type, req_amount in total_costs.items():
        ledgers[res_type].balance -= req_amount

    queue_item = MilitaryQueue(
        nation_id=nation_id,
        province_id=province_id,
        design_id=design_id,
        quantity=quantity,
        turns_remaining=design.build_time,
        facility_type=facility_type,
        created_at=utc_now(),
    )
    session.add(queue_item)
    await session.commit()
    await session.refresh(queue_item)

    logger.info("Enqueued military production", queue_id=queue_item.id, design=design.name, qty=quantity)
    return queue_item


async def cancel_military_queue(session: AsyncSession, nation_id: int, queue_id: int) -> bool:
    item = await session.get(MilitaryQueue, queue_id)
    if not item or item.nation_id != nation_id:
        return False

    design = await session.get(UnitDesign, item.design_id)
    if design:
        refunds = {res: float(amt) * item.quantity for res, amt in (design.production_cost or {}).items()}
        stmt = select(ResourceLedger).where(ResourceLedger.nation_id == nation_id)
        res = await session.execute(stmt)
        ledgers = {r.resource_type: r for r in res.scalars().all()}

        for res_type, ref_amount in refunds.items():
            if res_type in ledgers:
                ledgers[res_type].balance += ref_amount

    await session.delete(item)
    await session.commit()
    logger.info("Cancelled military queue item", queue_id=queue_id)
    return True


async def process_military_turn(session: AsyncSession, current_turn: int) -> Dict[str, Any]:
    logistics_cfg = config.get("military", {}).get("logistics", {})
    unsupplied_morale_pen = float(logistics_cfg.get("unsupplied_morale_penalty", 0.10))
    unsupplied_readiness_pen = float(logistics_cfg.get("unsupplied_readiness_penalty", 0.20))

    # 1. Advance Production Queues
    q_res = await session.execute(select(MilitaryQueue))
    queues = q_res.scalars().all()
    completed_units_count = 0

    for q in queues:
        q.turns_remaining -= 1
        if q.turns_remaining <= 0:
            f_stmt = select(MilitaryFormation).where(
                MilitaryFormation.nation_id == q.nation_id,
                MilitaryFormation.province_id == q.province_id,
                MilitaryFormation.design_id == q.design_id,
            )
            f_res = await session.execute(f_stmt)
            formation = f_res.scalar_one_or_none()

            if formation:
                formation.quantity += q.quantity
                formation.updated_at = utc_now()
            else:
                formation = MilitaryFormation(
                    nation_id=q.nation_id,
                    province_id=q.province_id,
                    design_id=q.design_id,
                    quantity=q.quantity,
                    experience=0.0,
                    morale=1.0,
                    fuel_status=1.0,
                    ammo_status=1.0,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(formation)

            completed_units_count += q.quantity
            await session.delete(q)

    # 2. Active Formations Logistics & Upkeep
    f_res = await session.execute(select(MilitaryFormation))
    formations = f_res.scalars().all()

    design_ids = {f.design_id for f in formations}
    designs = {}
    if design_ids:
        d_res = await session.execute(select(UnitDesign).where(UnitDesign.id.in_(design_ids)))
        designs = {d.id: d for d in d_res.scalars().all()}

    ledger_res = await session.execute(select(ResourceLedger))
    ledgers_by_nation: Dict[int, Dict[str, ResourceLedger]] = {}
    for l in ledger_res.scalars().all():
        ledgers_by_nation.setdefault(l.nation_id, {})[l.resource_type] = l

    for form in formations:
        des = designs.get(form.design_id)
        if not des:
            continue

        n_ledgers = ledgers_by_nation.get(form.nation_id, {})
        money_upkeep = float((des.upkeep or {}).get("money", 0.0)) * form.quantity
        money_ledger = n_ledgers.get("money")
        has_money = money_ledger and money_ledger.balance >= money_upkeep

        if has_money and money_ledger:
            money_ledger.balance -= money_upkeep
        else:
            form.morale = max(0.0, form.morale - unsupplied_morale_pen)

        fuel_use = float((des.stats or {}).get("fuel_use", 0.0))
        if fuel_use > 0:
            fuel_req = (fuel_use / 10.0) * form.quantity
            gas_ledger = n_ledgers.get("gasoline") or n_ledgers.get("oil")
            if gas_ledger and gas_ledger.balance >= fuel_req:
                gas_ledger.balance -= fuel_req
                form.fuel_status = min(1.0, form.fuel_status + 0.1)
            else:
                form.fuel_status = max(0.0, form.fuel_status - unsupplied_readiness_pen)
                form.morale = max(0.0, form.morale - 0.05)

        munitions_ledger = n_ledgers.get("munitions")
        ammo_req = 1.0 * form.quantity
        if munitions_ledger and munitions_ledger.balance >= ammo_req:
            munitions_ledger.balance -= ammo_req
            form.ammo_status = min(1.0, form.ammo_status + 0.1)
        else:
            form.ammo_status = max(0.0, form.ammo_status - unsupplied_readiness_pen)

        if form.fuel_status > 0.5 and form.ammo_status > 0.5 and has_money:
            form.morale = min(1.0, form.morale + 0.05)
        form.experience = min(1.0, form.experience + float(logistics_cfg.get("peace_experience_gain", 0.01)))
        form.updated_at = utc_now()

    # 3. Expire Old Spy Intel
    await session.execute(delete(SpyIntel).where(SpyIntel.expires_at_turn <= current_turn))
    await session.flush()
    return {"completed_units": completed_units_count, "active_formations": len(formations)}


async def conduct_spy_mission(
    session: AsyncSession, spy_nation_id: int, target_nation_id: int, current_turn: int
) -> SpyIntel:
    if spy_nation_id == target_nation_id:
        raise ValueError("Cannot spy on your own nation.")

    logistics_cfg = config.get("military", {}).get("logistics", {})
    cost = float(logistics_cfg.get("spy_mission_cost_money", 5000))

    res = await session.execute(
        select(ResourceLedger).where(ResourceLedger.nation_id == spy_nation_id, ResourceLedger.resource_type == "money")
    )
    money_ledger = res.scalar_one_or_none()
    money_bal = money_ledger.balance if money_ledger else 0.0

    if money_bal < cost:
        raise ValueError(f"Insufficient funds ({money_bal:.2f} available, {cost:.2f} required).")

    money_ledger.balance -= cost

    intel_res = await session.execute(
        select(SpyIntel).where(SpyIntel.spy_nation_id == spy_nation_id, SpyIntel.target_nation_id == target_nation_id)
    )
    intel = intel_res.scalar_one_or_none()

    duration = int(logistics_cfg.get("spy_intel_duration_turns", 12))
    gain = float(logistics_cfg.get("spy_intel_level_per_mission", 0.5))

    if intel:
        intel.intel_level = min(1.0, intel.intel_level + gain)
        intel.expires_at_turn = current_turn + duration
    else:
        intel = SpyIntel(
            spy_nation_id=spy_nation_id,
            target_nation_id=target_nation_id,
            intel_level=gain,
            expires_at_turn=current_turn + duration,
            created_at=utc_now(),
        )
        session.add(intel)

    await session.commit()
    await session.refresh(intel)
    logger.info("Spy mission conducted", spy_nation=spy_nation_id, target=target_nation_id)
    return intel


async def get_visible_forces(
    session: AsyncSession, viewing_nation_id: int, target_nation_id: int, current_turn: int
) -> Dict[str, Any]:
    f_res = await session.execute(select(MilitaryFormation).where(MilitaryFormation.nation_id == target_nation_id))
    formations = f_res.scalars().all()

    design_ids = {f.design_id for f in formations}
    designs = {}
    if design_ids:
        d_res = await session.execute(select(UnitDesign).where(UnitDesign.id.in_(design_ids)))
        designs = {d.id: d for d in d_res.scalars().all()}

    is_own = (viewing_nation_id == target_nation_id)
    intel_level = 1.0 if is_own else 0.0

    if not is_own:
        intel_res = await session.execute(
            select(SpyIntel).where(
                SpyIntel.spy_nation_id == viewing_nation_id,
                SpyIntel.target_nation_id == target_nation_id,
                SpyIntel.expires_at_turn > current_turn,
            )
        )
        intel = intel_res.scalar_one_or_none()
        if intel:
            intel_level = intel.intel_level

    visible = []
    for f in formations:
        d = designs.get(f.design_id)
        d_name = d.name if d else "Unknown Model"
        cat = d.category if d else "unknown"

        if intel_level >= 1.0:
            visible.append({
                "id": f.id,
                "province_id": f.province_id,
                "design_name": d_name,
                "category": cat,
                "quantity": f.quantity,
                "experience": round(f.experience, 2),
                "morale": round(f.morale, 2),
                "fuel_status": round(f.fuel_status, 2),
                "ammo_status": round(f.ammo_status, 2),
                "stats": d.stats if d else {},
            })
        elif intel_level >= 0.5:
            visible.append({
                "province_id": f.province_id,
                "category": cat,
                "quantity_estimate": f.quantity,
                "morale_status": "High" if f.morale > 0.7 else "Low",
            })
        else:
            visible.append({"province_id": f.province_id, "category": "CLASSIFIED", "quantity_estimate": "Unknown"})

    return {
        "target_nation_id": target_nation_id,
        "intel_level": round(intel_level, 2),
        "fog_of_war_active": (intel_level < 1.0),
        "formations": visible,
    }
