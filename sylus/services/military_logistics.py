import math
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import (
    Nation, Province, Building, UnitDesign, ResourceLedger,
    MilitaryProductionQueue, MilitaryFormation, NationIntel, GlobalState, utc_now
)
from sylus.logging import get_logger

logger = get_logger(__name__)


def get_military_config() -> Dict[str, Any]:
    return config.get("military", {})


def get_category_facility_type(category: str) -> str:
    for fac_type, fac_data in get_military_config().get("facilities", {}).items():
        if category in fac_data.get("allowed_categories", []):
            return fac_type
    return "factory"


async def get_province_facility_capacity(session: AsyncSession, province_id: int, facility_type: str) -> int:
    cap_per_lvl = int(get_military_config().get("facilities", {}).get(facility_type, {}).get("capacity_per_level", 5))
    stmt = select(Building).where(Building.province_id == province_id, Building.building_type == facility_type, Building.turns_remaining == 0)
    res = await session.execute(stmt)
    return sum(b.level * cap_per_lvl for b in res.scalars().all())


async def enqueue_unit_production(
    session: AsyncSession, nation_id: int, province_id: int, design_id: int, quantity: int = 1
) -> MilitaryProductionQueue:
    if quantity <= 0:
        raise ValueError("Production quantity must be greater than 0.")
    nation = await session.get(Nation, nation_id)
    province = await session.get(Province, province_id)
    design = await session.get(UnitDesign, design_id)

    if not nation or not province or province.nation_id != nation_id or not design or design.nation_id != nation_id:
        raise ValueError("Invalid nation, province, or unit design ownership.")

    facility_type = get_category_facility_type(design.category)
    capacity = await get_province_facility_capacity(session, province_id, facility_type)
    if capacity <= 0:
        raise ValueError(f"No active {facility_type} operating in province {province.name}.")

    stmt_q = select(MilitaryProductionQueue).where(MilitaryProductionQueue.province_id == province_id, MilitaryProductionQueue.facility_type == facility_type)
    existing_queued_units = sum(q.quantity for q in (await session.execute(stmt_q)).scalars().all())
    if existing_queued_units + quantity > capacity:
        raise ValueError(f"Exceeds {facility_type} capacity limit in {province.name} (Capacity: {capacity}, Queued: {existing_queued_units}, Requested: {quantity}).")

    crew_per_unit = int(design.stats.get("crew", 1)) if isinstance(design.stats, dict) else 1
    total_crew_required = crew_per_unit * quantity
    if nation.soldiers < total_crew_required:
        raise ValueError(f"Insufficient soldiers. Required: {total_crew_required}, Available: {nation.soldiers}.")

    prod_cost = design.production_cost or {}
    total_cost = {res: float(amt) * quantity for res, amt in prod_cost.items()}
    ledgers = {r.resource_type: r for r in (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation_id))).scalars().all()}

    for res_type, cost_amount in total_cost.items():
        ledger = ledgers.get(res_type)
        if not ledger or ledger.balance < cost_amount:
            raise ValueError(f"Insufficient {res_type}. Needed: {cost_amount}, Available: {ledger.balance if ledger else 0.0}.")

    for res_type, cost_amount in total_cost.items():
        ledgers[res_type].balance -= cost_amount

    nation.soldiers -= total_crew_required
    now = utc_now()
    queue_item = MilitaryProductionQueue(
        nation_id=nation_id, province_id=province_id, design_id=design_id, facility_type=facility_type,
        quantity=quantity, completed_quantity=0, turns_remaining=design.build_time or 1, created_at=now
    )
    session.add(queue_item)
    await session.commit()
    await session.refresh(queue_item)
    logger.info("Enqueued military production", queue_id=queue_item.id, design=design.name, quantity=quantity)
    return queue_item


async def list_production_queue(session: AsyncSession, nation_id: int) -> List[MilitaryProductionQueue]:
    res = await session.execute(select(MilitaryProductionQueue).where(MilitaryProductionQueue.nation_id == nation_id).order_by(MilitaryProductionQueue.id.asc()))
    return list(res.scalars().all())


async def cancel_production_queue(session: AsyncSession, nation_id: int, queue_id: int) -> bool:
    queue_item = await session.get(MilitaryProductionQueue, queue_id)
    if not queue_item or queue_item.nation_id != nation_id:
        return False

    refund_ratio = float(get_military_config().get("logistics", {}).get("cancel_refund_ratio", 0.8))
    design = await session.get(UnitDesign, queue_item.design_id)
    if design:
        ledgers = {r.resource_type: r for r in (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation_id))).scalars().all()}
        for res_type, amt in (design.production_cost or {}).items():
            if res_type in ledgers:
                ledgers[res_type].balance += float(amt) * queue_item.quantity * refund_ratio

        crew_per_unit = int(design.stats.get("crew", 1)) if isinstance(design.stats, dict) else 1
        nation = await session.get(Nation, nation_id)
        if nation:
            nation.soldiers += crew_per_unit * queue_item.quantity

    await session.delete(queue_item)
    await session.commit()
    logger.info("Cancelled production queue item", queue_id=queue_id, nation_id=nation_id)
    return True


async def train_soldiers(session: AsyncSession, nation_id: int, quantity: int) -> Tuple[bool, str]:
    if quantity <= 0:
        return False, "Quantity must be greater than 0."
    nation = await session.get(Nation, nation_id)
    if not nation or nation.unemployed < quantity:
        return False, f"Insufficient unemployed population. Need {quantity}."

    cost_per_soldier = float(get_military_config().get("manpower", {}).get("soldier_training_cost_money", 50.0))
    total_cost = cost_per_soldier * quantity
    money_ledger = (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation_id, ResourceLedger.resource_type == "money"))).scalar_one_or_none()

    if not money_ledger or money_ledger.balance < total_cost:
        return False, f"Insufficient money. Need ${total_cost:,.2f}."

    money_ledger.balance -= total_cost
    nation.unemployed -= quantity
    nation.soldiers += quantity
    await session.commit()
    logger.info("Trained soldiers", nation_id=nation_id, quantity=quantity, cost=total_cost)
    return True, f"Successfully trained {quantity:,} soldiers for ${total_cost:,.2f}."


async def process_military_turn(session: AsyncSession) -> Dict[str, Any]:
    mil_cfg = get_military_config()
    log_cfg = mil_cfg.get("logistics", {})
    fuel_rate, ammo_rate = float(log_cfg.get("fuel_per_unit", 1.0)), float(log_cfg.get("ammo_per_unit", 1.0))
    decay_rate, unsupplied_penalty = float(log_cfg.get("supply_decay_rate", 0.2)), float(log_cfg.get("unsupplied_morale_penalty", 10.0))
    supplied_recovery, exp_gain = float(log_cfg.get("supplied_morale_recovery", 5.0)), float(log_cfg.get("experience_gain_per_turn", 1.0))
    max_morale, max_exp = float(log_cfg.get("max_morale", 100.0)), float(log_cfg.get("max_experience", 100.0))

    queue_items = (await session.execute(select(MilitaryProductionQueue))).scalars().all()
    completed_count = 0
    for q in queue_items:
        q.turns_remaining -= 1
        if q.turns_remaining <= 0:
            stmt_f = select(MilitaryFormation).where(MilitaryFormation.nation_id == q.nation_id, MilitaryFormation.province_id == q.province_id, MilitaryFormation.design_id == q.design_id)
            formation = (await session.execute(stmt_f)).scalar_one_or_none()
            now = utc_now()
            if formation:
                formation.quantity += q.quantity
                formation.updated_at = now
            else:
                formation = MilitaryFormation(
                    nation_id=q.nation_id, province_id=q.province_id, design_id=q.design_id, quantity=q.quantity,
                    experience=10.0, morale=max_morale, fuel_supply=1.0, ammo_supply=1.0, created_at=now, updated_at=now
                )
                session.add(formation)
            completed_count += q.quantity
            await session.delete(q)

    formations = (await session.execute(select(MilitaryFormation))).scalars().all()
    nation_formations: Dict[int, List[MilitaryFormation]] = {}
    for f in formations:
        nation_formations.setdefault(f.nation_id, []).append(f)

    for n_id, f_list in nation_formations.items():
        ledgers = {r.resource_type: r for r in (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == n_id))).scalars().all()}
        for f in f_list:
            design = await session.get(UnitDesign, f.design_id)
            if not design:
                continue

            upkeep = design.upkeep or {}
            money_upkeep = float(upkeep.get("money", 10.0)) * f.quantity
            stats = design.stats or {}
            fuel_needed = float(stats.get("fuel_use", 0.0)) * fuel_rate * f.quantity
            ammo_needed = ammo_rate * f.quantity if float(stats.get("attack", 0.0)) > 0 else 0.0

            money_led = ledgers.get("money")
            money_ok = money_led and money_led.balance >= money_upkeep
            if money_ok and money_led:
                money_led.balance -= money_upkeep

            gas_led = ledgers.get("gasoline")
            gas_ok = (fuel_needed == 0.0) or (gas_led and gas_led.balance >= fuel_needed)
            if fuel_needed > 0 and gas_led and gas_ok:
                gas_led.balance -= fuel_needed
                f.fuel_supply = 1.0
            elif fuel_needed > 0:
                f.fuel_supply = max(0.0, f.fuel_supply - decay_rate)

            mun_led = ledgers.get("munitions")
            mun_ok = (ammo_needed == 0.0) or (mun_led and mun_led.balance >= ammo_needed)
            if ammo_needed > 0 and mun_led and mun_ok:
                mun_led.balance -= ammo_needed
                f.ammo_supply = 1.0
            elif ammo_needed > 0:
                f.ammo_supply = max(0.0, f.ammo_supply - decay_rate)

            if money_ok and gas_ok and mun_ok:
                f.morale = min(max_morale, f.morale + supplied_recovery)
                f.experience = min(max_exp, f.experience + exp_gain)
            else:
                f.morale = max(0.0, f.morale - unsupplied_penalty)

            f.updated_at = utc_now()

    logger.info("Processed military turn", completed_units=completed_count, active_formations=len(formations))
    return {"completed_units": completed_count, "active_formations_processed": len(formations)}


async def resupply_formations(session: AsyncSession, nation_id: int) -> Tuple[bool, str]:
    formations = (await session.execute(select(MilitaryFormation).where(MilitaryFormation.nation_id == nation_id))).scalars().all()
    if not formations:
        return False, "No active military formations to resupply."

    log_cfg = get_military_config().get("logistics", {})
    cost_gas = float(log_cfg.get("resupply_cost_gasoline", 10.0))
    cost_mun = float(log_cfg.get("resupply_cost_munitions", 10.0))

    ledgers = {r.resource_type: r for r in (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation_id))).scalars().all()}
    gas_led, mun_led = ledgers.get("gasoline"), ledgers.get("munitions")

    resupplied = 0
    for f in formations:
        if f.fuel_supply < 1.0 and gas_led and gas_led.balance >= cost_gas:
            gas_led.balance -= cost_gas
            f.fuel_supply = 1.0
            resupplied += 1
        if f.ammo_supply < 1.0 and mun_led and mun_led.balance >= cost_mun:
            mun_led.balance -= cost_mun
            f.ammo_supply = 1.0
            resupplied += 1
        f.updated_at = utc_now()

    await session.commit()
    return True, f"Successfully resupplied forces across {resupplied} supply lines."


async def spy_on_nation(session: AsyncSession, spy_nation_id: int, target_nation_id: int) -> Tuple[bool, str]:
    if spy_nation_id == target_nation_id:
        return False, "You cannot spy on your own nation."

    spy_nation, target_nation = await session.get(Nation, spy_nation_id), await session.get(Nation, target_nation_id)
    if not spy_nation or not target_nation:
        return False, "Nation not found."

    fog_cfg = get_military_config().get("fog_of_war", {})
    cost = float(fog_cfg.get("spy_cost_money", 1000.0))
    duration = int(fog_cfg.get("spy_intel_duration_turns", 5))

    money_led = (await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == spy_nation_id, ResourceLedger.resource_type == "money"))).scalar_one_or_none()
    if not money_led or money_led.balance < cost:
        return False, f"Insufficient money for spy mission. Cost: ${cost:,.2f}."

    state = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
    current_turn = state.turn_number if state else 1

    money_led.balance -= cost
    intel = (await session.execute(select(NationIntel).where(NationIntel.spy_nation_id == spy_nation_id, NationIntel.target_nation_id == target_nation_id))).scalar_one_or_none()

    if intel:
        intel.intel_level = 2
        intel.expires_at_turn = current_turn + duration
    else:
        intel = NationIntel(spy_nation_id=spy_nation_id, target_nation_id=target_nation_id, intel_level=2, expires_at_turn=current_turn + duration, created_at=utc_now())
        session.add(intel)

    await session.commit()
    logger.info("Spy operation executed", spy_nation=spy_nation_id, target_nation=target_nation_id)
    return True, f"Spy mission successful! Gained Intel Level 2 on {target_nation.name} for {duration} turns."


async def get_visible_nation_forces(session: AsyncSession, viewer_nation_id: int, target_nation_id: int) -> Tuple[int, List[Dict[str, Any]]]:
    formations = (await session.execute(select(MilitaryFormation).where(MilitaryFormation.nation_id == target_nation_id))).scalars().all()
    fog_cfg = get_military_config().get("fog_of_war", {})
    lower_ratio, upper_ratio = float(fog_cfg.get("estimate_lower_ratio", 0.7)), float(fog_cfg.get("estimate_upper_ratio", 1.3))

    if viewer_nation_id == target_nation_id:
        intel_level = 3
    else:
        state = (await session.execute(select(GlobalState).where(GlobalState.id == 1))).scalar_one_or_none()
        current_turn = state.turn_number if state else 1
        intel = (await session.execute(select(NationIntel).where(NationIntel.spy_nation_id == viewer_nation_id, NationIntel.target_nation_id == target_nation_id, NationIntel.expires_at_turn >= current_turn))).scalar_one_or_none()
        intel_level = intel.intel_level if intel else int(fog_cfg.get("default_intel_level", 0))

    visible_forces = []
    for f in formations:
        design = await session.get(UnitDesign, f.design_id)
        prov = await session.get(Province, f.province_id)
        prov_name = prov.display_name if prov and prov.display_name else (prov.name if prov else "Unknown Province")

        if intel_level >= 2:
            visible_forces.append({
                "formation_id": f.id, "province_name": prov_name, "design_name": design.name if design else "Unknown Model",
                "category": design.category if design else "unknown", "quantity": f.quantity, "experience": f.experience,
                "morale": f.morale, "fuel_supply": f.fuel_supply, "ammo_supply": f.ammo_supply, "fog_of_war": False
            })
        elif intel_level == 1:
            lower = max(1, int(f.quantity * lower_ratio))
            upper = int(f.quantity * upper_ratio) + 1
            visible_forces.append({
                "formation_id": f.id, "province_name": prov_name, "design_name": f"[{design.category.capitalize() if design else 'Military'} Force]",
                "category": design.category if design else "unknown", "quantity_range": f"{lower}-{upper}", "fog_of_war": True
            })
        else:
            visible_forces.append({
                "formation_id": f.id, "province_name": prov_name, "design_name": "[Hidden by Fog of War]",
                "category": "Classified", "quantity_range": "Unknown Strength", "fog_of_war": True
            })

    return intel_level, visible_forces
