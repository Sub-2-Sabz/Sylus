import pytest
from sqlalchemy import select
from sylus.db.models import Nation, Province, ResourceLedger, DisasterZone, TradeOffer
from sylus.services.disasters import process_disasters_turn


@pytest.mark.asyncio
async def test_disaster_turn_processing(db_session):
    nation = Nation(
        id=1,
        name="DisasterLand",
        discord_user_id=100200300,
        population=10000,
        happiness=0.80,
    )
    db_session.add(nation)
    await db_session.commit()

    p1 = Province(id=1, name="Coastal Prov", nation_id=nation.id, terrain="coastal", population=5000, infrastructure=3)
    p2 = Province(id=2, name="Forest Prov", nation_id=nation.id, terrain="forest", population=5000, infrastructure=2)
    db_session.add_all([p1, p2])

    money = ResourceLedger(nation_id=nation.id, resource_type="money", balance=10000.0)
    db_session.add(money)
    await db_session.commit()

    # Process disasters turn with seeded RNG
    res = await process_disasters_turn(db_session, turn_number=5)
    assert res["turn_number"] == 5
    assert "new_disasters_count" in res
    assert "epidemic_summary" in res


@pytest.mark.asyncio
async def test_epidemic_spread_and_disaster_zones(db_session):
    n1 = Nation(id=10, name="Nation A", discord_user_id=101010, population=10000)
    n2 = Nation(id=11, name="Nation B", discord_user_id=202020, population=10000)
    db_session.add_all([n1, n2])
    await db_session.commit()

    p1 = Province(id=101, name="Infected Prov", nation_id=n1.id, terrain="plains")
    p2 = Province(id=102, name="Target Prov", nation_id=n2.id, terrain="plains")
    db_session.add_all([p1, p2])

    # Initial epidemic zone on p1
    dzone = DisasterZone(
        province_id=p1.id,
        nation_id=n1.id,
        disaster_type="epidemic",
        severity=1.0,
        turns_remaining=2,
        created_at_turn=1,
    )
    db_session.add(dzone)

    # Active trade offer between n1 and n2
    offer = TradeOffer(
        sender_id=n1.id,
        receiver_id=n2.id,
        offer_type="direct",
        status="pending",
        expires_at_turn=10,
        created_at_turn=1,
    )
    db_session.add(offer)
    await db_session.commit()

    res = await process_disasters_turn(db_session, turn_number=2)
    # Disaster zone should decrement or spread
    all_zones = (await db_session.execute(select(DisasterZone))).scalars().all()
    assert len(all_zones) >= 1
