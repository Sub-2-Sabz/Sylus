import pytest
from sqlalchemy import select

from sylus.db.models import Nation, Contract, ContractSignatory, ContractObligation, NationReputation
from sylus.services.trade import get_or_create_ledger
from sylus.services.contract import (
    create_contract,
    sign_contract,
    process_contract_turn,
    file_appeal,
    admin_resolve_appeal,
    get_or_create_reputation,
)


@pytest.mark.asyncio
async def test_contract_creation_and_both_party_signing(db_session):
    party_a = Nation(name="RepA", discord_user_id=7001)
    party_b = Nation(name="RepB", discord_user_id=7002)
    db_session.add_all([party_a, party_b])
    await db_session.commit()

    c = await create_contract(
        db_session,
        title="Trade Pact Alpha",
        contract_type="trade_agreement",
        party_a_id=party_a.id,
        party_b_id=party_b.id,
        duration_turns=10,
        obligations_data=[],
        penalty_type="fine",
    )
    await db_session.commit()

    assert c.status == "pending_signatures"
    assert c.is_immutable is False
    assert "Trade Pact Alpha" in c.plain_language_summary

    # Party A auto-signed upon creation. Party B signs:
    await sign_contract(db_session, c.id, party_b.id, current_turn=1)
    await db_session.commit()

    assert c.status == "active"
    assert c.is_immutable is True
    assert c.start_turn == 1
    assert c.end_turn == 11


@pytest.mark.asyncio
async def test_automated_contract_obligation_execution(db_session):
    party_a = Nation(name="Creditor", discord_user_id=8001)
    party_b = Nation(name="Debtor", discord_user_id=8002)
    db_session.add_all([party_a, party_b])
    await db_session.commit()

    # Debtor has $500 money
    ledger_b = await get_or_create_ledger(db_session, party_b.id, "money")
    ledger_b.balance = 500.0
    await db_session.commit()

    obligations = [
        {
            "payer_id": party_b.id,
            "payee_id": party_a.id,
            "obligation_type": "recurring_per_turn",
            "asset_type": "resource",
            "asset_id": "money",
            "amount": 100.0,
        }
    ]

    c = await create_contract(
        db_session,
        title="Loan Repayment",
        contract_type="loan_debt",
        party_a_id=party_a.id,
        party_b_id=party_b.id,
        duration_turns=5,
        obligations_data=obligations,
    )
    await sign_contract(db_session, c.id, party_b.id, current_turn=1)
    await db_session.commit()

    # Process turn 1
    summary = await process_contract_turn(db_session, current_turn=1)
    await db_session.commit()

    assert summary["executed"] == 1
    assert summary["breached"] == 0

    ledger_a = await get_or_create_ledger(db_session, party_a.id, "money")
    assert ledger_a.balance == 100.0
    assert ledger_b.balance == 400.0


@pytest.mark.asyncio
async def test_contract_breach_on_insufficient_balance(db_session):
    party_a = Nation(name="Supplier", discord_user_id=9001)
    party_b = Nation(name="BrokeNation", discord_user_id=9002)
    db_session.add_all([party_a, party_b])
    await db_session.commit()

    # BrokeNation has $0 money
    ledger_b = await get_or_create_ledger(db_session, party_b.id, "money")
    ledger_b.balance = 0.0
    await db_session.commit()

    obligations = [
        {
            "payer_id": party_b.id,
            "payee_id": party_a.id,
            "obligation_type": "recurring_per_turn",
            "asset_type": "resource",
            "asset_id": "money",
            "amount": 100.0,
        }
    ]

    c = await create_contract(
        db_session,
        title="Resource Supply Pact",
        contract_type="resource_supply",
        party_a_id=party_a.id,
        party_b_id=party_b.id,
        duration_turns=5,
        obligations_data=obligations,
    )
    await sign_contract(db_session, c.id, party_b.id, current_turn=1)
    await db_session.commit()

    # Process turn 1 -> obligation fails!
    summary = await process_contract_turn(db_session, current_turn=1)
    await db_session.commit()

    assert summary["breached"] == 1
    assert c.status == "breached"
    assert c.appeal_ends_at_turn == 4  # 1 + appeal_window_turns(3)

    rep_b = await get_or_create_reputation(db_session, party_b.id)
    assert rep_b.score < 100.0  # Reputation score penalized!
    assert rep_b.contracts_breached == 1


@pytest.mark.asyncio
async def test_appeal_and_admin_override(db_session):
    party_a = Nation(name="Nation One", discord_user_id=9101)
    party_b = Nation(name="Nation Two", discord_user_id=9102)
    db_session.add_all([party_a, party_b])
    await db_session.commit()

    obligations = [
        {
            "payer_id": party_b.id,
            "payee_id": party_a.id,
            "obligation_type": "recurring_per_turn",
            "asset_type": "resource",
            "asset_id": "money",
            "amount": 100.0,
        }
    ]

    c = await create_contract(
        db_session,
        title="Pact",
        contract_type="custom",
        party_a_id=party_a.id,
        party_b_id=party_b.id,
        duration_turns=5,
        obligations_data=obligations,
    )
    await sign_contract(db_session, c.id, party_b.id, current_turn=1)
    await db_session.commit()

    # Breach contract
    await process_contract_turn(db_session, current_turn=1)
    await db_session.commit()
    assert c.status == "breached"

    # Party B files appeal
    appeal = await file_appeal(db_session, c.id, party_b.id, "Emergency system glitch", current_turn=2)
    await db_session.commit()

    assert c.status == "under_appeal"

    # Admin upholds appeal
    await admin_resolve_appeal(db_session, appeal.id, admin_user_id=9999, uphold=True, admin_notes="Appeal granted")
    await db_session.commit()

    assert c.status == "active"
    assert appeal.status == "upheld"


@pytest.mark.asyncio
async def test_contract_natural_expiration_and_reputation_bonus(db_session):
    party_a = Nation(name="Ally Alpha", discord_user_id=9201)
    party_b = Nation(name="Ally Beta", discord_user_id=9202)
    db_session.add_all([party_a, party_b])
    await db_session.commit()

    c = await create_contract(
        db_session,
        title="Non Aggression Pact",
        contract_type="non_aggression_pact",
        party_a_id=party_a.id,
        party_b_id=party_b.id,
        duration_turns=2,
        obligations_data=[],
    )
    await sign_contract(db_session, c.id, party_b.id, current_turn=1)
    await db_session.commit()

    assert c.end_turn == 3

    # Run turn 3 (end turn reached)
    summary = await process_contract_turn(db_session, current_turn=3)
    await db_session.commit()

    assert summary["expired"] == 1
    assert c.status == "expired"

    rep_a = await get_or_create_reputation(db_session, party_a.id)
    assert rep_a.score > 100.0  # Fulfillment bonus awarded!
    assert rep_a.contracts_fulfilled == 1
