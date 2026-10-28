import pytest
from sqlalchemy import select
from sylus.db.models import Nation, Province, ResourceLedger
from sylus.services.demographics import update_demographics_turn, evaluate_unrest_ladder, apply_unrest_response


@pytest.mark.asyncio
async def test_update_demographics_and_unrest_ladder(db_session):
    nation = Nation(
        id=1,
        name="Testia",
        discord_user_id=123456789,
        population=10000,
        happiness=0.50, # Below 0.60 threshold -> protests
        tax_rate=0.20,
    )
    db_session.add(nation)
    await db_session.commit()

    summary = await update_demographics_turn(db_session)
    await db_session.refresh(nation)

    assert nation.workers == 7000
    assert nation.soldiers == 500
    assert nation.unemployed == 2500
    assert nation.unrest_level in ["protests", "normal"]
    assert "protests" in summary or "normal" in summary


@pytest.mark.asyncio
async def test_civil_war_secession(db_session):
    nation = Nation(
        id=2,
        name="Rebelia",
        discord_user_id=987654321,
        population=20000,
        happiness=0.10, # Very low happiness -> civil war
    )
    db_session.add(nation)
    await db_session.commit()

    cap_prov = Province(id=10, name="Capital", nation_id=nation.id, is_capital=True)
    other_prov = Province(id=11, name="Rebel Prov", nation_id=nation.id, is_capital=False)
    db_session.add_all([cap_prov, other_prov])
    await db_session.commit()

    unrest_res = await evaluate_unrest_ladder(db_session, nation)
    assert unrest_res["unrest_level"] == "civil_war"
    assert nation.unrest_level == "civil_war"


@pytest.mark.asyncio
async def test_apply_unrest_response(db_session):
    nation = Nation(
        id=3,
        name="Reformia",
        discord_user_id=111222333,
        population=10000,
        happiness=0.45,
        unrest_level="riots",
    )
    db_session.add(nation)
    await db_session.commit()

    money = ResourceLedger(nation_id=nation.id, resource_type="money", balance=5000.0)
    db_session.add(money)
    await db_session.commit()

    # Apply reforms
    res = await apply_unrest_response(db_session, nation.id, "reforms")
    assert res["success"] is True
    assert res["unrest_level"] in ["protests", "normal"]

    await db_session.refresh(money)
    assert money.balance == 3000.0 # 5000 - 2000 cost
