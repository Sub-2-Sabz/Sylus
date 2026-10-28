from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import (
    Nation,
    NationReputation,
    Contract,
    ContractSignatory,
    ContractObligation,
    ContractAppeal,
    AuditLog,
    utc_now,
)
from sylus.services.trade import verify_and_deduct_asset, add_asset_to_nation
from sylus.logging import get_logger

logger = get_logger(__name__)


async def get_or_create_reputation(session: AsyncSession, nation_id: int) -> NationReputation:
    stmt = select(NationReputation).where(NationReputation.nation_id == nation_id)
    rep = (await session.execute(stmt)).scalar_one_or_none()
    if rep is None:
        init_score = float(config.get("contracts.reputation.initial_score", 100.0))
        rep = NationReputation(nation_id=nation_id, score=init_score, contracts_fulfilled=0, contracts_breached=0)
        session.add(rep)
        await session.flush()
    return rep


async def update_reputation_score(session: AsyncSession, nation_id: int, delta: float, fulfilled: bool = False, breached: bool = False) -> None:
    rep = await get_or_create_reputation(session, nation_id)
    min_score = float(config.get("contracts.reputation.min_score", 0.0))
    max_score = float(config.get("contracts.reputation.max_score", 200.0))
    rep.score = max(min_score, min(max_score, rep.score + delta))
    if fulfilled:
        rep.contracts_fulfilled += 1
    if breached:
        rep.contracts_breached += 1


def generate_plain_summary(
    title: str,
    contract_type: str,
    duration_turns: int,
    parties_names: List[str],
    obligations: List[Dict[str, Any]],
    penalty_type: str,
) -> str:
    parties_str = " & ".join(parties_names)
    summary_lines = [
        f"**Contract:** {title} ({contract_type.replace('_', ' ').title()})",
        f"**Parties:** {parties_str}",
        f"**Duration:** {duration_turns} turns",
        "**Obligations:**",
    ]
    if not obligations:
        summary_lines.append("  - Non-aggression / alliance accord (no direct asset transfers).")
    else:
        for ob in obligations:
            ob_type = ob.get("obligation_type", "recurring_per_turn").replace("_", " ")
            summary_lines.append(
                f"  - Party #{ob['payer_id']} transfers {ob['amount']} {ob['asset_type']}:{ob['asset_id']} to Party #{ob['payee_id']} ({ob_type})"
            )
    summary_lines.append(f"**Stated Breach Penalty:** {penalty_type.replace('_', ' ').title()}")
    return "\n".join(summary_lines)


async def create_contract(
    session: AsyncSession,
    title: str,
    contract_type: str,
    party_a_id: int,
    party_b_id: int,
    duration_turns: int,
    obligations_data: List[Dict[str, Any]],
    penalty_type: str = "fine",
    penalty_details: Optional[Dict[str, Any]] = None,
) -> Contract:
    party_a = await session.get(Nation, party_a_id)
    party_b = await session.get(Nation, party_b_id)
    if not party_a or not party_b:
        raise ValueError("Invalid signatory nation.")

    summary = generate_plain_summary(
        title=title,
        contract_type=contract_type,
        duration_turns=duration_turns,
        parties_names=[party_a.name, party_b.name],
        obligations=obligations_data,
        penalty_type=penalty_type,
    )

    contract = Contract(
        title=title,
        contract_type=contract_type,
        status="pending_signatures",
        duration_turns=duration_turns,
        plain_language_summary=summary,
        stated_penalty_type=penalty_type,
        stated_penalty_details=penalty_details or {},
        appeal_window_turns=int(config.get("contracts.appeal_window_turns", 3)),
        is_immutable=False,
    )
    session.add(contract)
    await session.flush()

    # Creator auto-signs party_a
    sig_a = ContractSignatory(contract_id=contract.id, nation_id=party_a_id, role="party_a", signed=True, signed_at=utc_now())
    sig_b = ContractSignatory(contract_id=contract.id, nation_id=party_b_id, role="party_b", signed=False)
    session.add_all([sig_a, sig_b])

    for ob in obligations_data:
        session.add(
            ContractObligation(
                contract_id=contract.id,
                payer_id=ob["payer_id"],
                payee_id=ob["payee_id"],
                obligation_type=ob.get("obligation_type", "recurring_per_turn"),
                asset_type=ob["asset_type"],
                asset_id=str(ob["asset_id"]),
                amount=float(ob["amount"]),
                status="pending",
            )
        )

    await session.flush()
    return contract


async def sign_contract(session: AsyncSession, contract_id: int, nation_id: int, current_turn: int) -> Contract:
    contract = await session.get(Contract, contract_id)
    if not contract or contract.status != "pending_signatures":
        raise ValueError("Contract is not awaiting signatures.")

    stmt = select(ContractSignatory).where(ContractSignatory.contract_id == contract_id, ContractSignatory.nation_id == nation_id)
    sig = (await session.execute(stmt)).scalar_one_or_none()
    if not sig:
        raise ValueError("You are not a signatory on this contract.")

    sig.signed = True
    sig.signed_at = utc_now()

    # Check if all signatories have signed
    stmt_all = select(ContractSignatory).where(ContractSignatory.contract_id == contract_id)
    all_sigs = (await session.execute(stmt_all)).scalars().all()
    if all(s.signed for s in all_sigs):
        contract.status = "active"
        contract.start_turn = current_turn
        contract.end_turn = current_turn + contract.duration_turns
        contract.is_immutable = True  # Immutable once signed!

    await session.flush()
    return contract


async def execute_obligation(session: AsyncSession, obligation: ContractObligation) -> bool:
    success = await verify_and_deduct_asset(
        session, obligation.payer_id, obligation.asset_type, obligation.asset_id, obligation.amount
    )
    if success:
        await add_asset_to_nation(
            session, obligation.payee_id, obligation.asset_type, obligation.asset_id, obligation.amount
        )
        obligation.status = "fulfilled"
        return True
    else:
        obligation.status = "failed"
        return False


async def enforce_penalty(session: AsyncSession, contract: Contract, breaching_nation_id: int) -> None:
    penalty_type = contract.stated_penalty_type
    details = contract.stated_penalty_details or {}
    fine_amount = float(details.get("fine_amount", 500.0))

    if penalty_type == "fine":
        await verify_and_deduct_asset(session, breaching_nation_id, "resource", "money", fine_amount)
    elif penalty_type in ("temporary_ban", "permanent_ban"):
        # Log severity audit
        session.add(
            AuditLog(
                action_type="contract_ban_enforced",
                entity_type="contract",
                entity_id=contract.id,
                details={"nation_id": breaching_nation_id, "penalty_type": penalty_type},
            )
        )

    contract.status = "enforced"


async def process_contract_turn(session: AsyncSession, current_turn: int) -> Dict[str, int]:
    summary = {"executed": 0, "breached": 0, "expired": 0, "enforced": 0}

    # 1. Active Contracts - Obligations
    stmt_active = select(Contract).where(Contract.status == "active")
    active_contracts = (await session.execute(stmt_active)).scalars().all()

    for c in active_contracts:
        # Check if expired naturally
        if c.end_turn and current_turn >= c.end_turn:
            c.status = "expired"
            summary["expired"] += 1
            # Bonus reputation for fulfillment
            stmt_sigs = select(ContractSignatory).where(ContractSignatory.contract_id == c.id)
            sigs = (await session.execute(stmt_sigs)).scalars().all()
            fulfilled_bonus = float(config.get("contracts.reputation.fulfillment_bonus", 5.0))
            for s in sigs:
                await update_reputation_score(session, s.nation_id, fulfilled_bonus, fulfilled=True)
            continue

        # Process obligations
        stmt_obs = select(ContractObligation).where(ContractObligation.contract_id == c.id)
        obs = (await session.execute(stmt_obs)).scalars().all()
        for ob in obs:
            if ob.obligation_type == "one_time" and ob.status == "fulfilled":
                continue
            res = await execute_obligation(session, ob)
            ob.last_executed_turn = current_turn
            if res:
                summary["executed"] += 1
            else:
                # OBLIGATION FAILED -> CONTRACT BREACHED!
                c.status = "breached"
                c.appeal_ends_at_turn = current_turn + c.appeal_window_turns
                summary["breached"] += 1

                breach_penalty = float(config.get("contracts.reputation.breach_penalty", -25.0))
                # If penalty in config is positive delta (e.g. 25.0), ensure it subtracts
                if breach_penalty > 0:
                    breach_penalty = -breach_penalty
                await update_reputation_score(session, ob.payer_id, breach_penalty, breached=True)
                break

    # 2. Breached Contracts past appeal window without appeal -> enforce penalty
    stmt_breached = select(Contract).where(
        Contract.status == "breached", Contract.appeal_ends_at_turn <= current_turn
    )
    breached_contracts = (await session.execute(stmt_breached)).scalars().all()
    for c in breached_contracts:
        stmt_failed_ob = select(ContractObligation).where(
            ContractObligation.contract_id == c.id, ContractObligation.status == "failed"
        )
        failed_ob = (await session.execute(stmt_failed_ob)).scalar_one_or_none()
        breaching_id = failed_ob.payer_id if failed_ob else c.signatories[0].nation_id
        await enforce_penalty(session, c, breaching_id)
        summary["enforced"] += 1

    await session.flush()
    return summary


async def file_appeal(session: AsyncSession, contract_id: int, appellant_nation_id: int, reason: str, current_turn: int) -> ContractAppeal:
    contract = await session.get(Contract, contract_id)
    if not contract or contract.status != "breached":
        raise ValueError("Contract is not in breached status or appeal window closed.")

    stmt_sig = select(ContractSignatory).where(
        ContractSignatory.contract_id == contract_id, ContractSignatory.nation_id == appellant_nation_id
    )
    sig = (await session.execute(stmt_sig)).scalar_one_or_none()
    if not sig:
        raise ValueError("You are not a party to this contract.")

    contract.status = "under_appeal"
    appeal = ContractAppeal(
        contract_id=contract_id,
        appellant_nation_id=appellant_nation_id,
        reason=reason,
        status="pending",
        appeal_turn=current_turn,
    )
    session.add(appeal)
    await session.flush()
    return appeal


async def admin_resolve_appeal(
    session: AsyncSession, appeal_id: int, admin_user_id: int, uphold: bool, admin_notes: str = ""
) -> Contract:
    appeal = await session.get(ContractAppeal, appeal_id)
    if not appeal or appeal.status != "pending":
        raise ValueError("Appeal is not pending.")

    contract = await session.get(Contract, appeal.contract_id)
    appeal.admin_override_by = admin_user_id
    appeal.admin_notes = admin_notes

    if uphold:
        appeal.status = "upheld"
        contract.status = "active"  # Restore active status
    else:
        appeal.status = "rejected"
        stmt_failed_ob = select(ContractObligation).where(
            ContractObligation.contract_id == contract.id, ContractObligation.status == "failed"
        )
        failed_ob = (await session.execute(stmt_failed_ob)).scalar_one_or_none()
        breaching_id = failed_ob.payer_id if failed_ob else contract.signatories[0].nation_id
        await enforce_penalty(session, contract, breaching_id)

    await session.flush()
    return contract
