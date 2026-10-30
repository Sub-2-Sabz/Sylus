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

    p1 = await db_session.get(Province, 1)
    p2 = await db_session.get(Province, 2)
    p1.nation_id = nation.id
    p1.terrain = "coastal"
    p2.nation_id = nation.id
    p2.terrain = "forest"

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

    p1 = await db_session.get(Province, 101)
    p2 = await db_session.get(Province, 102)
    p1.nation_id = n1.id
    p2.nation_id = n2.id

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
