import random
from typing import Dict, Any, Optional, Tuple
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import (
    Nation, Province, ResourceLedger, Building, DisasterZone, NationTech,
    UnitDesign, MilitaryFormation, AuditLog, NationReputation
)
from sylus.db.war_models import War, WarLog
from sylus.services.war_modifier import evaluate_combat_modifiers


def _get_nuke_cfg() -> Dict[str, Any]:
    return config.get("war", {}).get("nuclear_weapons", {})


async def check_nuclear_eligibility(
    session: AsyncSession, striker_id: int
) -> Tuple[bool, str]:
    """Validates research, uranium/plutonium stockpiles, and delivery system availability."""
    cfg = _get_nuke_cfg()
    req_tech = cfg.get("required_tech", "nuclear_weapons")
    req_res = cfg.get("required_resources", {"uranium": 50.0, "plutonium": 20.0})

    # Tech check
    tech_stmt = select(NationTech).where(
        NationTech.nation_id == striker_id, NationTech.tech_id == req_tech
    )
    if not (await session.execute(tech_stmt)).scalar_one_or_none():
        return False, f"Missing required nuclear technology: '{req_tech}'."

    # Resource check
    for r_type, req_amount in req_res.items():
        res_stmt = select(ResourceLedger).where(
            ResourceLedger.nation_id == striker_id, ResourceLedger.resource_type == r_type
        )
        ledger = (await session.execute(res_stmt)).scalar_one_or_none()
        if not ledger or ledger.balance < req_amount:
            curr = ledger.balance if ledger else 0.0
            return False, f"Insufficient {r_type}: {curr:.1f}/{req_amount:.1f} required."

    # Delivery system design check
    ds_stmt = select(UnitDesign).where(
        UnitDesign.nation_id == striker_id,
        UnitDesign.category.in_(["missiles", "bombers", "fighters"])
    )
    designs = (await session.execute(ds_stmt)).scalars().all()
    if not designs:
        return False, "No suitable delivery system design (missiles/bombers) found."

    return True, ""


async def execute_nuclear_strike(
    session: AsyncSession,
    war_id: int,
    striker_id: int,
    province_id: int,
    current_turn: int = 1,
    seed: Optional[float] = None,
) -> WarLog:
    """Executes nuclear strike attempt with interception check, devastation, fallout, and penalties."""
    war = await session.get(War, war_id)
    if not war or war.status != "active":
        raise ValueError("War is not active or does not exist.")

    eligible, reason = await check_nuclear_eligibility(session, striker_id)
    if not eligible:
        raise ValueError(reason)

    target_prov = await session.get(Province, province_id)
    if not target_prov or target_prov.nation_id is None:
        raise ValueError("Invalid target province.")

    defender_id = target_prov.nation_id
    striker = await session.get(Nation, striker_id)
    defender = await session.get(Nation, defender_id)

    cfg = _get_nuke_cfg()
    req_res = cfg.get("required_resources", {"uranium": 50.0, "plutonium": 20.0})

    # Deduct nuclear materials
    for r_type, req_amount in req_res.items():
        res_stmt = select(ResourceLedger).where(
            ResourceLedger.nation_id == striker_id, ResourceLedger.resource_type == r_type
        )
        ledger = (await session.execute(res_stmt)).scalar_one_or_none()
        if ledger:
            ledger.balance = max(0.0, ledger.balance - req_amount)

    # Calculate defender air defense interception chance
    def_forms_stmt = select(MilitaryFormation).where(
        MilitaryFormation.nation_id == defender_id,
        MilitaryFormation.province_id == province_id,
    )
    def_forms = (await session.execute(def_forms_stmt)).scalars().all()

    has_air_def = any(
        f.design and f.design.category in ( "air_defense", "fighters") for f in def_forms
    )

    interception_cfg = cfg.get("interception", {})
    base_chance = interception_cfg.get("base_air_defense_chance", 0.40) if has_air_def else 0.0
    max_chance = interception_cfg.get("max_interception_chance", 0.85)
    interception_chance = min(max_chance, base_chance)

    roll = seed if seed is not None else random.random()
    intercepted = (roll < interception_chance)

    if intercepted:
        summary = f"🚀 Nuclear Strike Intercepted! Air defenses over {target_prov.name} successfully destroyed incoming warhead."
        war_log = WarLog(
            war_id=war.id,
            turn_number=current_turn,
            action_type="nuclear_strike",
            attacker_id=striker_id,
            defender_id=defender_id,
            province_id=province_id,
            victory_tier="Failure",
            attacker_score=0.0,
            defender_score=100.0,
            roll_diff=-50.0,
            casualties={},
            loot_resources={},
            modifiers_applied={"intercepted": True, "interception_chance": interception_chance},
            summary=summary,
        )
        session.add(war_log)
        await session.flush()
        await session.refresh(war_log)
        return war_log

    # Detonation Devastation
    dev_cfg = cfg.get("devastation", {})
    mortality = dev_cfg.get("population_mortality_rate", 0.60)
    rep_penalty = dev_cfg.get("reputation_penalty", 50.0)
    hap_penalty = dev_cfg.get("happiness_penalty", 0.30)
    ws_penalty = dev_cfg.get("war_support_penalty", 0.25)
    fallout_turns = dev_cfg.get("fallout_duration_turns", 12)

    # Population mortality & infrastructure reset
    pop_killed = int(target_prov.population * mortality)
    target_prov.population = max(0, target_prov.population - pop_killed)
    target_prov.infrastructure = 1

    # Destroy all buildings in province
    await session.execute(delete(Building).where(Building.province_id == province_id))

    # Spawn Fallout Disaster Zone
    fallout_dz = DisasterZone(
        province_id=province_id,
        nation_id=defender_id,
        disaster_type="fallout",
        severity=2.0,
        turns_remaining=fallout_turns,
        created_at_turn=current_turn,
    )
    session.add(fallout_dz)

    def_hap_pen = dev_cfg.get("defender_happiness_penalty", 0.40)
    def_ws_pen = dev_cfg.get("defender_war_support_penalty", 0.30)

    # Striker penalties
    if striker:
        striker.happiness = max(0.0, striker.happiness - hap_penalty)
        striker.war_support = max(0.0, striker.war_support - ws_penalty)

        # Apply global reputation penalty to striker
        rep_stmt = select(NationReputation).where(NationReputation.nation_id == striker_id)
        rep = (await session.execute(rep_stmt)).scalar_one_or_none()
        if rep:
            rep.score = max(0.0, rep.score - rep_penalty)

    # Defender penalties
    if defender:
        defender.happiness = max(0.0, defender.happiness - def_hap_pen)
        defender.war_support = max(0.0, defender.war_support - def_ws_pen)

    summary = f"☢️ NUCLEAR DETONATION in {target_prov.name}! Killed {pop_killed:,} citizens, wiped infrastructure/buildings, spawned nuclear fallout zone for {fallout_turns} turns."
    war_log = WarLog(
        war_id=war.id,
        turn_number=current_turn,
        action_type="nuclear_strike",
        attacker_id=striker_id,
        defender_id=defender_id,
        province_id=province_id,
        victory_tier="Immense Triumph",
        attacker_score=1000.0,
        defender_score=0.0,
        roll_diff=1000.0,
        casualties={"defender_population_killed": pop_killed},
        loot_resources={},
        modifiers_applied={"intercepted": False, "fallout_turns": fallout_turns},
        summary=summary,
    )
    session.add(war_log)

    session.add(AuditLog(
        action_type="nuclear_strike_executed",
        entity_type="province",
        entity_id=province_id,
        actor_id=striker.discord_user_id if striker else None,
        details={"war_id": war_id, "pop_killed": pop_killed, "fallout_turns": fallout_turns},
    ))

    await session.flush()
    await session.refresh(war_log)
    return war_log
