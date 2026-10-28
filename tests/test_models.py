import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from sylus.db.models import GlobalState, Nation, Province, ResourceLedger, AuditLog

@pytest.mark.asyncio
async def test_global_state_creation(db_session):
    now = datetime.now(timezone.utc)
    gs = GlobalState(turn_number=1, next_turn_at=now)
    db_session.add(gs)
    await db_session.commit()

    result = await db_session.execute(select(GlobalState))
    state = result.scalar_one()
    assert state.turn_number == 1
    assert state.next_turn_at is not None

@pytest.mark.asyncio
async def test_nation_and_related_models(db_session):
    nation = Nation(name="Aethelgard", discord_user_id=123456789)
    db_session.add(nation)
    await db_session.commit()
    await db_session.refresh(nation)

    province = Province(name="Capital", nation_id=nation.id, terrain="hills")
    ledger = ResourceLedger(nation_id=nation.id, resource_type="gold", balance=1000.0)
    db_session.add_all([province, ledger])
    await db_session.commit()

    res = await db_session.execute(select(Nation).where(Nation.id == nation.id))
    fetched_nation = res.scalar_one()
    assert fetched_nation.name == "Aethelgard"

    p_res = await db_session.execute(select(Province).where(Province.nation_id == nation.id))
    fetched_province = p_res.scalar_one()
    assert fetched_province.name == "Capital"
    assert fetched_province.terrain == "hills"

    r_res = await db_session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation.id))
    fetched_ledger = r_res.scalar_one()
    assert fetched_ledger.resource_type == "gold"
    assert fetched_ledger.balance == 1000.0

@pytest.mark.asyncio
async def test_audit_log(db_session):
    log = AuditLog(
        action_type="REGISTER_NATION",
        entity_type="Nation",
        entity_id=1,
        actor_id=123456789,
        details={"name": "Aethelgard"}
    )
    db_session.add(log)
    await db_session.commit()

    res = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
    fetched_log = res.scalar_one()
    assert fetched_log.action_type == "REGISTER_NATION"
    assert fetched_log.details == {"name": "Aethelgard"}
