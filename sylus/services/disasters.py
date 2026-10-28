import random
from typing import Dict, Any, List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, Province, Building, ResourceLedger, DisasterZone, TradeOffer, Contract
from sylus.logging import get_logger

logger = get_logger(__name__)


async def process_disasters_turn(session: AsyncSession, turn_number: int) -> Dict[str, Any]:
    """Processes turn disasters using seeded RNG, managing disaster zones, epidemic spread, and damage mitigation."""
    rng = random.Random(f"disaster_{turn_number}")

    # 1. Decay existing active disaster zones
    await session.execute(
        delete(DisasterZone).where(DisasterZone.turns_remaining <= 1)
    )
    res_active = await session.execute(select(DisasterZone))
    active_zones = res_active.scalars().all()
    for z in active_zones:
        z.turns_remaining -= 1

    # Load provinces, nations, buildings
    prov_res = await session.execute(select(Province))
    provinces = {p.id: p for p in prov_res.scalars().all()}

    nation_res = await session.execute(select(Nation))
    nations = {n.id: n for n in nation_res.scalars().all()}

    disaster_types = config.get("disasters.types", {})
    global_base_chance = float(config.get("disasters.global_disaster_base_chance", 0.15))

    occurred_disasters: List[Dict[str, Any]] = []

    # 2. Roll new disasters per province/nation
    if rng.random() < global_base_chance and provinces:
        # Pick 1 to 3 affected provinces
        sample_size = min(len(provinces), rng.randint(1, 3))
        selected_prov_ids = rng.sample(list(provinces.keys()), sample_size)

        for pid in selected_prov_ids:
            prov = provinces[pid]
            # Select compatible disaster type
            possible_types = []
            for dtype, spec in disaster_types.items():
                prereqs = spec.get("terrain_prereq", [])
                if not prereqs or prov.terrain in prereqs:
                    possible_types.append((dtype, float(spec.get("base_probability", 0.01))))

            if not possible_types:
                continue

            # Weighted pick
            dtypes, weights = zip(*possible_types)
            chosen_dtype = rng.choices(dtypes, weights=weights, k=1)[0]
            spec = disaster_types[chosen_dtype]

            # Apply disaster damage & mitigation
            impact = await _apply_disaster_impact(session, prov, nations.get(prov.nation_id), chosen_dtype, spec)

            # Create DisasterZone record
            dzone = DisasterZone(
                province_id=prov.id,
                nation_id=prov.nation_id,
                disaster_type=chosen_dtype,
                severity=1.0,
                turns_remaining=int(spec.get("duration_turns", 1)),
                created_at_turn=turn_number,
            )
            session.add(dzone)
            occurred_disasters.append({"province_id": prov.id, "type": chosen_dtype, **impact})

    # 3. Handle Epidemic spread along trade links and province borders
    epidemic_summary = await _process_epidemic_spread(session, turn_number, rng, provinces, nations)

    return {
        "turn_number": turn_number,
        "new_disasters_count": len(occurred_disasters),
        "disasters": occurred_disasters,
        "epidemic_summary": epidemic_summary,
    }


async def _apply_disaster_impact(
    session: AsyncSession,
    province: Province,
    nation: Optional[Nation],
    disaster_type: str,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculates disaster damage and applies mitigation factors."""
    pop_kill_pct = float(spec.get("pop_kill_percent", 0.0))
    infra_dmg = int(spec.get("infra_damage", 0))
    money_loss = float(spec.get("money_loss", 0.0))
    hap_impact = float(spec.get("happiness_impact", 0.0))

    # Check hospital mitigation in province if epidemic or disaster
    hospitals = 0
    if nation:
        b_res = await session.execute(
            select(Building).where(Building.province_id == province.id, Building.building_type == "hospital")
        )
        hospitals = len(b_res.scalars().all())

    hosp_mitigation = float(config.get("disasters.mitigation.hospital_health_bonus", 0.10)) * hospitals
    effective_pop_kill = max(0.0, pop_kill_pct * (1.0 - hosp_mitigation))

    # Check infrastructure mitigation
    infra_mitigation_pct = float(config.get("disasters.mitigation.infrastructure_damage_reduction_pct", 0.15))
    effective_infra_dmg = max(0, int(infra_dmg * (1.0 - (province.infrastructure * infra_mitigation_pct))))

    province.population = max(10, int(province.population * (1.0 - effective_pop_kill)))
    province.infrastructure = max(1, province.infrastructure - effective_infra_dmg)

    actual_money_lost = 0.0
    if nation:
        nation.happiness = max(0.0, min(1.0, nation.happiness + hap_impact))
        nation.population = max(10, int(nation.population * (1.0 - effective_pop_kill)))

        # Money loss mitigation via insurance config
        ins_pct = float(config.get("disasters.mitigation.insurance_money_recovery_pct", 0.30))
        effective_money_loss = money_loss * (1.0 - ins_pct)

        r_res = await session.execute(
            select(ResourceLedger).where(ResourceLedger.nation_id == nation.id, ResourceLedger.resource_type == "money")
        )
        money_ledger = r_res.scalar_one_or_none()
        if money_ledger:
            actual_money_lost = min(money_ledger.balance, effective_money_loss)
            money_ledger.balance -= actual_money_lost

    return {
        "pop_killed": int(province.population * effective_pop_kill),
        "infra_damaged": effective_infra_dmg,
        "money_lost": actual_money_lost,
    }


async def _process_epidemic_spread(
    session: AsyncSession,
    turn_number: int,
    rng: random.Random,
    provinces: Dict[int, Province],
    nations: Dict[int, Nation],
) -> Dict[str, Any]:
    """Spreads epidemics across adjacent province borders and active trade links."""
    active_epi_res = await session.execute(
        select(DisasterZone).where(DisasterZone.disaster_type == "epidemic")
    )
    active_epis = active_epi_res.scalars().all()
    if not active_epis:
        return {"spread_count": 0}

    trade_chance = float(config.get("disasters.epidemic_spread.trade_link_spread_chance", 0.30))
    border_chance = float(config.get("disasters.epidemic_spread.border_spread_chance", 0.40))

    infected_prov_ids = {ez.province_id for ez in active_epis}
    new_infections = 0

    # Trade links check (nations with active trade offers)
    active_trade_nations = set()
    trade_res = await session.execute(select(TradeOffer).where(TradeOffer.status == "pending"))
    for t in trade_res.scalars().all():
        active_trade_nations.add(t.sender_id)
        if t.receiver_id:
            active_trade_nations.add(t.receiver_id)

    for prov_id in list(infected_prov_ids):
        prov = provinces.get(prov_id)
        if not prov or not prov.nation_id:
            continue

        # Check border spread to adjacent uninfected provinces
        # Pick random uninfected province
        uninfected = [p for pid, p in provinces.items() if pid not in infected_prov_ids]
        if uninfected and rng.random() < border_chance:
            target_p = rng.choice(uninfected)
            dzone = DisasterZone(
                province_id=target_p.id,
                nation_id=target_p.nation_id,
                disaster_type="epidemic",
                severity=1.0,
                turns_remaining=2,
                created_at_turn=turn_number,
            )
            session.add(dzone)
            infected_prov_ids.add(target_p.id)
            new_infections += 1

        # Check trade link spread
        if prov.nation_id in active_trade_nations and rng.random() < trade_chance:
            other_nations = [nid for nid in active_trade_nations if nid != prov.nation_id]
            if other_nations:
                target_nid = rng.choice(other_nations)
                target_provs = [p for p in provinces.values() if p.nation_id == target_nid and p.id not in infected_prov_ids]
                if target_provs:
                    target_p = rng.choice(target_provs)
                    dzone = DisasterZone(
                        province_id=target_p.id,
                        nation_id=target_p.nation_id,
                        disaster_type="epidemic",
                        severity=1.0,
                        turns_remaining=2,
                        created_at_turn=turn_number,
                    )
                    session.add(dzone)
                    infected_prov_ids.add(target_p.id)
                    new_infections += 1

    return {"spread_count": new_infections}
