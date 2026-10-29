from typing import Dict, Any, Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, Province, ResourceLedger, TechLicense, MilitaryFormation, AuditLog
from sylus.db.war_models import War, PeaceTreaty, WarLog


def _get_treaty_cfg() -> Dict[str, Any]:
    return config.get("war", {}).get("peace_treaties", {})


async def create_peace_treaty(
    session: AsyncSession,
    war_id: int,
    proposer_id: int,
    reparations_per_turn: float = 0.0,
    reparations_resource: str = "money",
    territory_transfers: Optional[List[int]] = None,
    tech_licenses: Optional[List[str]] = None,
    demilitarization_max_soldiers: Optional[int] = None,
    current_turn: int = 1,
) -> PeaceTreaty:
    """Creates a proposed peace treaty with enforced terms."""
    war = await session.get(War, war_id)
    if not war or war.status != "active":
        raise ValueError("War is not active or does not exist.")

    if proposer_id not in (war.attacker_id, war.defender_id):
        raise ValueError("Proposer is not a participant in this war.")

    recipient_id = war.defender_id if proposer_id == war.attacker_id else war.attacker_id

    cfg = _get_treaty_cfg()
    max_rep = cfg.get("max_reparations_per_turn", 5000.0)
    max_terr = cfg.get("max_territory_transfers", 3)

    if reparations_per_turn > max_rep:
        raise ValueError(f"Reparations ({reparations_per_turn}) exceed max allowed ({max_rep}).")

    transfers = territory_transfers or []
    if len(transfers) > max_terr:
        raise ValueError(f"Territory transfers ({len(transfers)}) exceed max allowed ({max_terr}).")

    for pid in transfers:
        prov = await session.get(Province, pid)
        if not prov or prov.nation_id != recipient_id:
            raise ValueError(f"Province ID #{pid} does not belong to recipient nation.")

    default_duration = cfg.get("default_duration_turns", 24)
    treaty = PeaceTreaty(
        war_id=war_id,
        proposer_nation_id=proposer_id,
        recipient_nation_id=recipient_id,
        status="pending",
        duration_turns=default_duration,
        created_at_turn=current_turn,
        reparations_per_turn=reparations_per_turn,
        reparations_resource=reparations_resource,
        territory_transfers=transfers,
        tech_licenses=tech_licenses or [],
        demilitarization_max_soldiers=demilitarization_max_soldiers,
    )
    session.add(treaty)
    await session.flush()
    await session.refresh(treaty)
    return treaty


async def accept_peace_treaty(
    session: AsyncSession,
    treaty_id: int,
    acceptor_id: int,
    current_turn: int = 1,
) -> PeaceTreaty:
    """Accepts a peace treaty, immediately transferring territory and entering beige protection."""
    treaty = await session.get(PeaceTreaty, treaty_id)
    if not treaty or treaty.status != "pending":
        raise ValueError("Peace treaty is not pending or does not exist.")

    if acceptor_id != treaty.recipient_nation_id:
        raise ValueError("Only the designated recipient nation can accept this peace treaty.")

    war = await session.get(War, treaty.war_id)
    if not war:
        raise ValueError("Associated war not found.")

    treaty.status = "accepted"
    treaty.accepted_at_turn = current_turn

    # Execute immediate territory transfers
    for pid in treaty.territory_transfers:
        prov = await session.get(Province, pid)
        if prov:
            prov.nation_id = treaty.proposer_nation_id

    # Execute tech licenses
    for tech_id in treaty.tech_licenses:
        lic = TechLicense(
            licensor_id=treaty.recipient_nation_id,
            licensee_id=treaty.proposer_nation_id,
            tech_id=tech_id,
            royalty_per_turn=0.0,
        )
        session.add(lic)

    # Conclude war into beige protection
    beige_duration = config.get("war", {}).get("beige", {}).get("beige_duration_turns", 12)
    war.status = "beige"
    war.beige_until_turn = current_turn + beige_duration

    summary = f"Peace Treaty Accepted! Territory transferred: {treaty.territory_transfers}. War entered beige protection for {beige_duration} turns."
    war_log = WarLog(
        war_id=war.id,
        turn_number=current_turn,
        action_type="peace_treaty_accepted",
        attacker_id=treaty.proposer_nation_id,
        defender_id=treaty.recipient_nation_id,
        province_id=None,
        victory_tier="Ceasefire Accepted",
        attacker_score=0.0,
        defender_score=0.0,
        roll_diff=0.0,
        casualties={},
        loot_resources={},
        modifiers_applied={"territory_transfers": treaty.territory_transfers},
        summary=summary,
    )
    session.add(war_log)
    await session.flush()
    await session.refresh(treaty)
    return treaty


async def process_peace_treaties_turn(
    session: AsyncSession, current_turn: int
) -> Dict[str, int]:
    """Processes per-turn peace treaty obligations (reparations & demilitarization enforcement)."""
    stmt = select(PeaceTreaty).where(PeaceTreaty.status == "accepted")
    treaties = (await session.execute(stmt)).scalars().all()

    reparations_count = 0
    demil_enforced_count = 0

    for tr in treaties:
        if tr.accepted_at_turn and current_turn > (tr.accepted_at_turn + tr.duration_turns):
            tr.status = "expired"
            continue

        # Reparations transfer
        if tr.reparations_per_turn > 0.0:
            rec_res_stmt = select(ResourceLedger).where(
                ResourceLedger.nation_id == tr.recipient_nation_id,
                ResourceLedger.resource_type == tr.reparations_resource,
            )
            rec_res = (await session.execute(rec_res_stmt)).scalar_one_or_none()

            actual_transfer = min(rec_res.balance, tr.reparations_per_turn) if rec_res else 0.0
            if actual_transfer > 0.0:
                rec_res.balance -= actual_transfer

                prop_res_stmt = select(ResourceLedger).where(
                    ResourceLedger.nation_id == tr.proposer_nation_id,
                    ResourceLedger.resource_type == tr.reparations_resource,
                )
                prop_res = (await session.execute(prop_res_stmt)).scalar_one_or_none()
                if prop_res:
                    prop_res.balance += actual_transfer
                else:
                    session.add(ResourceLedger(
                        nation_id=tr.proposer_nation_id,
                        resource_type=tr.reparations_resource,
                        balance=actual_transfer,
                    ))
                reparations_count += 1

        # Demilitarization enforcement
        demil_hap_pen = _get_treaty_cfg().get("demilitarization_happiness_penalty", 0.05)
        if tr.demilitarization_max_soldiers is not None:
            rec_nat = await session.get(Nation, tr.recipient_nation_id)
            if rec_nat and rec_nat.soldiers > tr.demilitarization_max_soldiers:
                surplus = rec_nat.soldiers - tr.demilitarization_max_soldiers
                rec_nat.soldiers = tr.demilitarization_max_soldiers
                rec_nat.happiness = max(0.0, rec_nat.happiness - demil_hap_pen)
                demil_enforced_count += 1

    await session.flush()
    return {
        "reparations_executed": reparations_count,
        "demilitarizations_enforced": demil_enforced_count,
    }
