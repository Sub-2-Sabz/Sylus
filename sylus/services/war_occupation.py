from typing import Dict, Any, Optional, Tuple
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, Province, MilitaryFormation, Building
from sylus.db.war_models import War, WarLog, ProvinceOccupation, PortBlockade


def _get_war_cfg() -> Dict[str, Any]:
    return config.get("war", {})


async def advance_occupation(
    session: AsyncSession,
    war_id: int,
    occupier_id: int,
    province_id: int,
    victory_tier: str,
    current_turn: int = 1,
) -> Tuple[ProvinceOccupation, bool]:
    """Advances occupation progress on a province after a ground attack."""
    cfg = _get_war_cfg().get("occupation", {})
    progress_gains = cfg.get("progress_per_ground_victory", {
        "immense_triumph": 50.0,
        "moderate_success": 25.0,
        "pyrrhic": 10.0,
        "failure": 0.0,
    })

    key = victory_tier.lower().replace(" ", "_")
    gain = progress_gains.get(key, 0.0)

    stmt = select(ProvinceOccupation).where(
        ProvinceOccupation.war_id == war_id,
        ProvinceOccupation.province_id == province_id,
    )
    occ = (await session.execute(stmt)).scalar_one_or_none()

    if not occ:
        occ = ProvinceOccupation(
            war_id=war_id,
            province_id=province_id,
            occupier_nation_id=occupier_id,
            occupation_progress=0.0,
            insurgency_level=0.0,
            is_fully_occupied=False,
        )
        session.add(occ)

    occ.occupation_progress = min(100.0, occ.occupation_progress + gain)
    capital_captured = False

    if occ.occupation_progress >= 100.0 and not occ.is_fully_occupied:
        occ.is_fully_occupied = True
        prov = await session.get(Province, province_id)
        if prov and prov.is_capital:
            capital_captured = True
            war = await session.get(War, war_id)
            if war and war.status == "active":
                loser_id = war.defender_id if occupier_id == war.attacker_id else war.attacker_id
                await trigger_forced_surrender(session, war_id, loser_id, reason="Capital Captured", current_turn=current_turn)

    await session.flush()
    await session.refresh(occ)
    return occ, capital_captured


async def apply_blockade(
    session: AsyncSession,
    war_id: int,
    blockading_id: int,
    target_nation_id: int,
    province_id: Optional[int] = None,
) -> PortBlockade:
    """Applies or extends a port blockade against a nation or province."""
    cfg = _get_war_cfg().get("blockades", {})
    duration = cfg.get("duration_turns", 6)

    stmt = select(PortBlockade).where(
        PortBlockade.war_id == war_id,
        PortBlockade.blockaded_nation_id == target_nation_id,
    )
    if province_id:
        stmt = stmt.where(PortBlockade.province_id == province_id)

    blockade = (await session.execute(stmt)).scalar_one_or_none()
    if blockade:
        blockade.turns_remaining = duration
    else:
        blockade = PortBlockade(
            war_id=war_id,
            blockaded_nation_id=target_nation_id,
            blockading_nation_id=blockading_id,
            province_id=province_id,
            turns_remaining=duration,
        )
        session.add(blockade)

    await session.flush()
    await session.refresh(blockade)
    return blockade


async def process_occupation_and_blockades_turn(
    session: AsyncSession, current_turn: int
) -> Dict[str, int]:
    """Processes per-turn insurgency growth/decay and blockade duration countdowns."""
    cfg = _get_war_cfg().get("occupation", {})
    growth = cfg.get("insurgency_growth_per_turn", 5.0)
    decay_garrison = cfg.get("insurgency_decay_garrison", 10.0)
    revolting_thresh = cfg.get("revolting_threshold", 100.0)

    # Process occupations
    occ_stmt = select(ProvinceOccupation)
    occupations = (await session.execute(occ_stmt)).scalars().all()
    revolt_count = 0

    for occ in occupations:
        # Check garrison
        garrison_stmt = select(MilitaryFormation).where(
            MilitaryFormation.province_id == occ.province_id,
            MilitaryFormation.nation_id == occ.occupier_nation_id,
            MilitaryFormation.quantity > 0,
        )
        garrison = (await session.execute(garrison_stmt)).scalars().all()

        if garrison:
            occ.insurgency_level = max(0.0, occ.insurgency_level - decay_garrison)
        else:
            occ.insurgency_level = min(100.0, occ.insurgency_level + growth)

        # Check revolt
        if occ.insurgency_level >= revolting_thresh:
            occ.occupation_progress = 0.0
            occ.insurgency_level = 0.0
            occ.is_fully_occupied = False
            revolt_count += 1

    # Process blockades
    blk_stmt = select(PortBlockade)
    blockades = (await session.execute(blk_stmt)).scalars().all()
    expired_blockades = 0

    for blk in blockades:
        blk.turns_remaining -= 1
        if blk.turns_remaining <= 0:
            await session.delete(blk)
            expired_blockades += 1

    await session.flush()
    return {
        "occupations_processed": len(occupations),
        "revolts_occurred": revolt_count,
        "active_blockades": len(blockades) - expired_blockades,
        "expired_blockades": expired_blockades,
    }


async def check_war_exhaustion(
    session: AsyncSession, war_id: int, current_turn: int = 1
) -> Optional[int]:
    """Checks if either war participant is exhausted (war_support <= threshold) and triggers surrender."""
    war = await session.get(War, war_id)
    if not war or war.status != "active":
        return None

    thresh = _get_war_cfg().get("exhaustion", {}).get("exhaustion_threshold", 0.05)
    att = await session.get(Nation, war.attacker_id)
    dfn = await session.get(Nation, war.defender_id)

    if dfn and dfn.war_support <= thresh:
        await trigger_forced_surrender(session, war_id, dfn.id, reason="War Support Exhausted", current_turn=current_turn)
        return dfn.id
    elif att and att.war_support <= thresh:
        await trigger_forced_surrender(session, war_id, att.id, reason="War Support Exhausted", current_turn=current_turn)
        return att.id

    return None


async def trigger_forced_surrender(
    session: AsyncSession,
    war_id: int,
    loser_id: int,
    reason: str,
    current_turn: int = 1,
) -> WarLog:
    """Forces surrender of a nation, ending active conflict and placing war into beige state."""
    war = await session.get(War, war_id)
    if not war:
        raise ValueError("War not found")

    winner_id = war.attacker_id if loser_id == war.defender_id else war.defender_id
    beige_duration = _get_war_cfg().get("beige", {}).get("beige_duration_turns", 12)

    war.status = "beige"
    war.beige_until_turn = current_turn + beige_duration

    loser = await session.get(Nation, loser_id)
    winner = await session.get(Nation, winner_id)

    exh_cfg = _get_war_cfg().get("exhaustion", {})
    surr_hap_pen = exh_cfg.get("surrender_happiness_penalty", 0.20)
    surr_ws_pen = exh_cfg.get("surrender_war_support_penalty", 0.30)

    if loser:
        loser.happiness = max(0.0, loser.happiness - surr_hap_pen)
        loser.war_support = max(0.0, loser.war_support - surr_ws_pen)

    summary = f"Forced Surrender: {loser.name if loser else f'Nation #{loser_id}'} surrendered to {winner.name if winner else f'Nation #{winner_id}'} due to {reason}."
    war_log = WarLog(
        war_id=war.id,
        turn_number=current_turn,
        action_type="forced_surrender",
        attacker_id=winner_id,
        defender_id=loser_id,
        province_id=None,
        victory_tier="Immense Triumph",
        attacker_score=100.0,
        defender_score=0.0,
        roll_diff=100.0,
        casualties={},
        loot_resources={},
        modifiers_applied={"reason": reason},
        summary=summary,
    )
    session.add(war_log)
    await session.flush()
    await session.refresh(war_log)
    return war_log
