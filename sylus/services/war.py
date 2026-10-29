import random
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy import select, update, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import (
    Nation, Province, ResourceLedger, AuditLog, War, WarLog,
    MilitaryFormation, NationTech, NationReputation, utc_now
)
from sylus.services.war_modifier import evaluate_combat_modifiers
from sylus.services.war_occupation import advance_occupation, apply_blockade, check_war_exhaustion
from sylus.services.war_nukes import execute_nuclear_strike


def _get_war_cfg() -> Dict[str, Any]:
    return config.get("war", {})


async def declare_war(
    session: AsyncSession,
    attacker_id: int,
    defender_id: int,
    casus_belli: str = "none",
    current_turn: int = 1,
) -> War:
    """Declares a war between attacker and defender with validation checks."""
    if attacker_id == defender_id:
        raise ValueError("Cannot declare war on oneself.")

    attacker = await session.get(Nation, attacker_id)
    defender = await session.get(Nation, defender_id)
    if not attacker or not defender:
        raise ValueError("Attacker or defender nation does not exist.")

    cfg = _get_war_cfg().get("declarations", {})
    max_off = cfg.get("max_offensive_wars", 3)
    max_def = cfg.get("max_defensive_wars", 3)

    # Active offensive wars check
    stmt_off = select(War).where(War.attacker_id == attacker_id, War.status == "active")
    off_wars = (await session.execute(stmt_off)).scalars().all()
    if len(off_wars) >= max_off:
        raise ValueError(f"Attacker has reached max offensive war limit ({max_off}).")

    # Active defensive wars check
    stmt_def = select(War).where(War.defender_id == defender_id, War.status == "active")
    def_wars = (await session.execute(stmt_def)).scalars().all()
    if len(def_wars) >= max_def:
        raise ValueError(f"Defender has reached max defensive war limit ({max_def}).")

    # Existing war check between pair
    stmt_exist = select(War).where(
        War.status == "active",
        or_(
            and_(War.attacker_id == attacker_id, War.defender_id == defender_id),
            and_(War.attacker_id == defender_id, War.defender_id == attacker_id),
        )
    )
    if (await session.execute(stmt_exist)).scalar_one_or_none():
        raise ValueError("An active war already exists between these nations.")

    # Beige check
    stmt_beige = select(War).where(
        War.status == "beige",
        or_(War.attacker_id.in_([attacker_id, defender_id]), War.defender_id.in_([attacker_id, defender_id]))
    )
    beige_wars = (await session.execute(stmt_beige)).scalars().all()
    for bw in beige_wars:
        if bw.beige_until_turn and current_turn < bw.beige_until_turn:
            raise ValueError("Target or declaring nation is currently protected by beige mode.")

    # Score ratio range check
    min_ratio = cfg.get("min_score_ratio", 0.60)
    max_ratio = cfg.get("max_score_ratio", 1.75)
    ratio = defender.score / max(1.0, attacker.score)
    if ratio < min_ratio or ratio > max_ratio:
        raise ValueError(f"Target nation score ratio ({ratio:.2f}) is outside allowed war range [{min_ratio}, {max_ratio}].")

    # Unprovoked penalties
    valid_cb = cfg.get("casus_belli_types", [])
    if casus_belli not in valid_cb:
        casus_belli = "none"

    if casus_belli == "none":
        hap_pen = cfg.get("unprovoked_happiness_penalty", 0.10)
        ws_pen = cfg.get("unprovoked_war_support_penalty", 0.15)
        rep_pen = cfg.get("unprovoked_reputation_penalty", 15.0)

        attacker.happiness = max(0.0, attacker.happiness - hap_pen)
        attacker.war_support = max(0.0, attacker.war_support - ws_pen)

        rep_stmt = select(NationReputation).where(NationReputation.nation_id == attacker_id)
        rep = (await session.execute(rep_stmt)).scalar_one_or_none()
        if rep:
            rep.score = max(0.0, rep.score - rep_pen)

    ap_cfg = _get_war_cfg().get("action_points", {})
    max_ap = ap_cfg.get("max_action_points", 12)

    war = War(
        attacker_id=attacker_id,
        defender_id=defender_id,
        casus_belli=casus_belli,
        status="active",
        attacker_ap=max_ap,
        defender_ap=max_ap,
        attacker_fatigue=0.0,
        defender_fatigue=0.0,
        weather="clear",
        season="spring",
        created_at_turn=current_turn,
    )
    session.add(war)
    await session.flush()
    await session.refresh(war)

    session.add(AuditLog(
        action_type="war_declared",
        entity_type="war",
        entity_id=war.id,
        actor_id=attacker.discord_user_id,
        details={"attacker_id": attacker_id, "defender_id": defender_id, "casus_belli": casus_belli},
    ))
    await session.flush()
    return war


async def process_war_turn(session: AsyncSession, current_turn: int) -> Dict[str, int]:
    """Refills AP, decays fatigue, and updates beige states every turn."""
    stmt = select(War).where(War.status.in_(["active", "beige"]))
    wars = (await session.execute(stmt)).scalars().all()

    ap_cfg = _get_war_cfg().get("action_points", {})
    max_ap = ap_cfg.get("max_action_points", 12)
    refill = ap_cfg.get("ap_refill_per_turn", 12)
    fatigue_cfg = _get_war_cfg().get("modifiers", {}).get("fatigue", {})
    decay = fatigue_cfg.get("fatigue_decay_per_turn", 0.05)

    refilled_count = 0
    ended_beige_count = 0

    for w in wars:
        if w.status == "active":
            w.attacker_ap = min(max_ap, w.attacker_ap + refill)
            w.defender_ap = min(max_ap, w.defender_ap + refill)
            w.attacker_fatigue = max(0.0, w.attacker_fatigue - decay)
            w.defender_fatigue = max(0.0, w.defender_fatigue - decay)
            refilled_count += 1
        elif w.status == "beige":
            if w.beige_until_turn and current_turn >= w.beige_until_turn:
                w.status = "ended"
                w.ended_at_turn = current_turn
                ended_beige_count += 1

    return {"active_wars_refilled": refilled_count, "beige_wars_ended": ended_beige_count}


async def execute_war_action(
    session: AsyncSession,
    war_id: int,
    actor_id: int,
    action_type: str,
    province_id: Optional[int] = None,
    current_turn: int = 1,
    seed: Optional[float] = None,
) -> WarLog:
    """Executes a war action, computes stats & modifiers, determines victory tier, and records log."""
    war = await session.get(War, war_id)
    if not war or war.status != "active":
        raise ValueError("War is not active or does not exist.")

    is_attacker = (actor_id == war.attacker_id)
    is_defender = (actor_id == war.defender_id)
    if not is_attacker and not is_defender:
        raise ValueError("Actor is not a participant in this war.")

    opponent_id = war.defender_id if is_attacker else war.attacker_id
    actor_ap = war.attacker_ap if is_attacker else war.defender_ap

    ap_costs = _get_war_cfg().get("action_points", {}).get("action_ap_costs", {})
    cost = ap_costs.get(action_type, 3)
    if actor_ap < cost:
        raise ValueError(f"Insufficient Action Points ({actor_ap}/{cost}) for action {action_type}.")

    # Deduct AP and add fatigue
    if is_attacker:
        war.attacker_ap -= cost
        war.attacker_fatigue += _get_war_cfg().get("modifiers", {}).get("fatigue", {}).get("fatigue_per_action", 0.10)
    else:
        war.defender_ap -= cost
        war.defender_fatigue += _get_war_cfg().get("modifiers", {}).get("fatigue", {}).get("fatigue_per_action", 0.10)

    # Ceasefire special handling
    if action_type == "ceasefire_offer":
        return await _handle_ceasefire(session, war, actor_id, opponent_id, current_turn)

    # Nuclear strike special handling
    if action_type == "nuclear_strike":
        if not province_id:
            raise ValueError("Target province_id required for nuclear strike.")
        return await execute_nuclear_strike(session, war_id, actor_id, province_id, current_turn, seed)

    # Blockade special handling
    if action_type == "blockade":
        blk = await apply_blockade(session, war_id, actor_id, opponent_id, province_id)
        summary = f"Port Blockade established against Nation #{opponent_id} for {blk.turns_remaining} turns."
        war_log = WarLog(
            war_id=war.id, turn_number=current_turn, action_type="blockade",
            attacker_id=actor_id, defender_id=opponent_id, province_id=province_id,
            victory_tier="Moderate Success", attacker_score=50.0, defender_score=0.0, roll_diff=50.0,
            casualties={}, loot_resources={}, modifiers_applied={"turns_remaining": blk.turns_remaining},
            summary=summary,
        )
        session.add(war_log)
        await session.flush()
        await session.refresh(war_log)
        return war_log

    target_prov = await session.get(Province, province_id) if province_id else None
    terrain = target_prov.terrain if target_prov else "plains"
    infra_lvl = target_prov.infrastructure if target_prov else 1
    is_home = (target_prov.nation_id == opponent_id) if target_prov else False

    # Base formation forces
    actor_pow, actor_air, actor_nav = await _get_military_power(session, actor_id, province_id)
    opp_pow, opp_air, opp_nav = await _get_military_power(session, opponent_id, province_id)

    actor_nat = await session.get(Nation, actor_id)
    opp_nat = await session.get(Nation, opponent_id)

    actor_techs = len((await session.execute(select(NationTech).where(NationTech.nation_id == actor_id))).scalars().all())
    opp_techs = len((await session.execute(select(NationTech).where(NationTech.nation_id == opponent_id))).scalars().all())

    actor_fatigue = war.attacker_fatigue if is_attacker else war.defender_fatigue
    opp_fatigue = war.defender_fatigue if is_attacker else war.attacker_fatigue

    act_mods = evaluate_combat_modifiers(
        action_type=action_type, terrain=terrain, weather=war.weather, season=war.season,
        role="attacker" if is_attacker else "defender",
        fatigue=actor_fatigue, own_techs=actor_techs, enemy_techs=opp_techs,
        own_air_power=actor_air, enemy_air_power=opp_air, own_naval_power=actor_nav, enemy_naval_power=opp_nav,
        war_support=actor_nat.war_support if actor_nat else 0.70
    )
    opp_mods = evaluate_combat_modifiers(
        action_type=action_type, terrain=terrain, weather=war.weather, season=war.season,
        role="defender" if is_attacker else "attacker",
        fatigue=opp_fatigue, own_techs=opp_techs, enemy_techs=actor_techs,
        own_air_power=opp_air, enemy_air_power=actor_air, own_naval_power=opp_nav, enemy_naval_power=actor_nav,
        infrastructure_level=infra_lvl, is_home=is_home, war_support=opp_nat.war_support if opp_nat else 0.70
    )

    act_score = actor_pow * act_mods["total_multiplier"]
    opp_score = opp_pow * opp_mods["total_multiplier"]

    dice_min = _get_war_cfg().get("victory_tiers", {}).get("roll_dice_min", -15.0)
    dice_max = _get_war_cfg().get("victory_tiers", {}).get("roll_dice_max", 15.0)
    roll = seed if seed is not None else random.uniform(dice_min, dice_max)
    roll_diff = (act_score - opp_score) + roll

    thresholds = _get_war_cfg().get("victory_tiers", {}).get("thresholds", {})
    if roll_diff >= thresholds.get("immense_triumph", 40.0):
        v_tier = "Immense Triumph"
    elif roll_diff >= thresholds.get("moderate_success", 10.0):
        v_tier = "Moderate Success"
    elif roll_diff >= thresholds.get("pyrrhic", -10.0):
        v_tier = "Pyrrhic"
    else:
        v_tier = "Failure"

    casualties, loot = await _apply_combat_outcomes(session, actor_id, opponent_id, action_type, v_tier, target_prov)

    # Advance occupation on ground attacks
    if action_type == "ground_attack" and province_id:
        await advance_occupation(session, war.id, actor_id, province_id, v_tier, current_turn)

    summary = f"{action_type.replace('_', ' ').title()} executed: {v_tier}. Score Diff: {roll_diff:.1f} (Act: {act_score:.1f}, Opp: {opp_score:.1f})"
    war_log = WarLog(
        war_id=war.id,
        turn_number=current_turn,
        action_type=action_type,
        attacker_id=actor_id,
        defender_id=opponent_id,
        province_id=province_id,
        victory_tier=v_tier,
        attacker_score=round(act_score, 2),
        defender_score=round(opp_score, 2),
        roll_diff=round(roll_diff, 2),
        casualties=casualties,
        loot_resources=loot,
        modifiers_applied={"actor": act_mods["breakdown"], "opponent": opp_mods["breakdown"]},
        summary=summary,
    )
    session.add(war_log)
    await session.flush()

    # Check for war exhaustion / surrender
    await check_war_exhaustion(session, war.id, current_turn)

    await session.refresh(war_log)
    return war_log


async def _handle_ceasefire(
    session: AsyncSession, war: War, actor_id: int, opponent_id: int, current_turn: int
) -> WarLog:
    beige_duration = _get_war_cfg().get("beige", {}).get("beige_duration_turns", 12)
    if war.ceasefire_offered_by and war.ceasefire_offered_by != actor_id:
        # Both parties agreed
        war.status = "beige"
        war.beige_until_turn = current_turn + beige_duration
        war.ceasefire_offered_by = None
        tier = "Ceasefire Accepted"
        summary = f"Ceasefire accepted. War entering beige protection for {beige_duration} turns."
    else:
        war.ceasefire_offered_by = actor_id
        tier = "Ceasefire Offered"
        summary = "Ceasefire offered to opponent."

    war_log = WarLog(
        war_id=war.id, turn_number=current_turn, action_type="ceasefire_offer",
        attacker_id=actor_id, defender_id=opponent_id, province_id=None,
        victory_tier=tier, attacker_score=0.0, defender_score=0.0, roll_diff=0.0,
        casualties={}, loot_resources={}, modifiers_applied={}, summary=summary
    )
    session.add(war_log)
    await session.flush()
    await session.refresh(war_log)
    return war_log


async def _get_military_power(session: AsyncSession, nation_id: int, province_id: Optional[int]) -> Tuple[float, float, float]:
    stmt = select(MilitaryFormation).where(MilitaryFormation.nation_id == nation_id)
    if province_id:
        stmt = stmt.where(MilitaryFormation.province_id == province_id)
    formations = (await session.execute(stmt)).scalars().all()

    total_pow = 10.0  # Base militia floor
    air_pow = 0.0
    nav_pow = 0.0

    for f in formations:
        f_pow = f.quantity * (f.experience / 10.0) * (f.morale / 100.0)
        total_pow += f_pow
        if f.design and f.design.category in ("fighters", "bombers", "drones", "helicopters"):
            air_pow += f_pow
        elif f.design and f.design.category in ("warships", "submarines"):
            nav_pow += f_pow

    return total_pow, air_pow, nav_pow


async def _apply_combat_outcomes(
    session: AsyncSession, actor_id: int, opponent_id: int, action_type: str, victory_tier: str, target_prov: Optional[Province]
) -> Tuple[Dict[str, int], Dict[str, float]]:
    vt_cfg = _get_war_cfg().get("victory_tiers", {})
    key = victory_tier.lower().replace(" ", "_")
    c_ratios = vt_cfg.get("casualty_ratios", {}).get(key, {"attacker": 0.15, "defender": 0.25})
    loot_ratio = vt_cfg.get("loot_ratios", {}).get(key, 0.05)

    # Losses
    act_stmt = select(MilitaryFormation).where(MilitaryFormation.nation_id == actor_id)
    opp_stmt = select(MilitaryFormation).where(MilitaryFormation.nation_id == opponent_id)
    if target_prov:
        opp_stmt = opp_stmt.where(MilitaryFormation.province_id == target_prov.id)

    act_forms = (await session.execute(act_stmt)).scalars().all()
    opp_forms = (await session.execute(opp_stmt)).scalars().all()

    act_loss = 0
    opp_loss = 0

    for f in act_forms:
        loss = int(f.quantity * c_ratios["attacker"])
        if loss > 0:
            f.quantity = max(0, f.quantity - loss)
            act_loss += loss

    for f in opp_forms:
        loss = int(f.quantity * c_ratios["defender"])
        if loss > 0:
            f.quantity = max(0, f.quantity - loss)
            opp_loss += loss

    # Looting
    looted: Dict[str, float] = {}
    if loot_ratio > 0.0:
        opp_res_stmt = select(ResourceLedger).where(ResourceLedger.nation_id == opponent_id)
        opp_res = (await session.execute(opp_res_stmt)).scalars().all()
        for r in opp_res:
            amt = r.balance * loot_ratio
            if amt > 0.0:
                r.balance -= amt
                looted[r.resource_type] = round(amt, 2)
                act_res_stmt = select(ResourceLedger).where(ResourceLedger.nation_id == actor_id, ResourceLedger.resource_type == r.resource_type)
                act_r = (await session.execute(act_res_stmt)).scalar_one_or_none()
                if act_r:
                    act_r.balance += amt
                else:
                    session.add(ResourceLedger(nation_id=actor_id, resource_type=r.resource_type, balance=amt))

    # Infrastructure damage
    infra_dmg = vt_cfg.get("infrastructure_damage", {}).get(key, 0)
    if target_prov and infra_dmg > 0:
        target_prov.infrastructure = max(1, target_prov.infrastructure - infra_dmg)

    return {"actor_casualties": act_loss, "opponent_casualties": opp_loss}, looted
