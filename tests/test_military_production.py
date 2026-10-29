import pytest
from sqlalchemy import select

from sylus.db.models import (
    Nation, Province, Building, ResourceLedger, UnitDesign,
    MilitaryQueue, MilitaryFormation, SpyIntel
)
from sylus.services.military_production import (
    enqueue_military_production,
    cancel_military_queue,
    recruit_manpower,
    conduct_spy_mission,
    get_visible_forces,
    process_military_turn,
)
from sylus.services.military import create_unit_design


@pytest.mark.asyncio
async def test_manpower_recruitment(db_session):
    nation = Nation(
        name="Sparta",
        discord_user_id=1001,
        unemployed=1000,
        soldiers=100,
    )
    db_session.add(nation)
    await db_session.commit()
    await db_session.refresh(nation)

    # Add money ledger
    money = ResourceLedger(nation_id=nation.id, resource_type="money", balance=5000.0)
    db_session.add(money)
    await db_session.commit()

    # Recruit 200 soldiers
    updated = await recruit_manpower(db_session, nation.id, 200)
    assert updated.soldiers == 300
    assert updated.unemployed == 800
    assert money.balance == 3000.0  # 200 * 10 cost


@pytest.mark.asyncio
async def test_military_production_and_capacity_limits(db_session):
    nation = Nation(name="Athens", discord_user_id=1002)
    db_session.add(nation)
    await db_session.commit()
    await db_session.refresh(nation)

    province = Province(name="Attica", nation_id=nation.id)
    db_session.add(province)
    await db_session.commit()
    await db_session.refresh(province)

    # Add arms factory building (capacity 5)
    factory = Building(
        province_id=province.id,
        nation_id=nation.id,
        building_type="factory",
        level=1,
        turns_remaining=0,
    )
    db_session.add(factory)

    # Add resources
    money = ResourceLedger(nation_id=nation.id, resource_type="money", balance=50000.0)
    munitions = ResourceLedger(nation_id=nation.id, resource_type="munitions", balance=1000.0)
    db_session.add_all([money, munitions])
    await db_session.commit()

    # Create infantry design
    design = await create_unit_design(
        db_session, nation.id, "Hoplite-I", "infantry", {}
    )

    # Enqueue 3 units (within capacity 5)
    q_item = await enqueue_military_production(
        db_session, nation.id, province.id, design.id, quantity=3
    )
    assert q_item.quantity == 3
    assert q_item.turns_remaining == 1

    # Attempting to enqueue 3 more units exceeds capacity (3 + 3 = 6 > 5)
    with pytest.raises(ValueError, match="capacity limit reached"):
        await enqueue_military_production(
            db_session, nation.id, province.id, design.id, quantity=3
        )


@pytest.mark.asyncio
async def test_military_turn_advancement_and_logistics(db_session):
    nation = Nation(name="Rome", discord_user_id=1003)
    db_session.add(nation)
    await db_session.commit()
    await db_session.refresh(nation)

    province = Province(name="Latium", nation_id=nation.id)
    db_session.add(province)
    await db_session.commit()
    await db_session.refresh(province)

    factory = Building(province_id=province.id, nation_id=nation.id, building_type="factory", level=2, turns_remaining=0)
    db_session.add(factory)

    money = ResourceLedger(nation_id=nation.id, resource_type="money", balance=50000.0)
    munitions = ResourceLedger(nation_id=nation.id, resource_type="munitions", balance=100.0)
    gasoline = ResourceLedger(nation_id=nation.id, resource_type="gasoline", balance=100.0)
    steel = ResourceLedger(nation_id=nation.id, resource_type="steel", balance=500.0)
    db_session.add_all([money, munitions, gasoline, steel])
    await db_session.commit()

    design = await create_unit_design(db_session, nation.id, "Legion-Infantry", "infantry", {})

    q_item = await enqueue_military_production(db_session, nation.id, province.id, design.id, quantity=2)

    # Process turn: queue finishes and creates MilitaryFormation
    summary = await process_military_turn(db_session, current_turn=1)
    assert summary["completed_units"] == 2

    # Verify active formation
    res = await db_session.execute(select(MilitaryFormation).where(MilitaryFormation.nation_id == nation.id))
    formation = res.scalar_one()
    assert formation.quantity == 2
    assert formation.morale == 1.0


@pytest.mark.asyncio
async def test_fog_of_war_and_spy_intel(db_session):
    spy_nation = Nation(name="MI6", discord_user_id=1004)
    target_nation = Nation(name="KGB", discord_user_id=1005)
    db_session.add_all([spy_nation, target_nation])
    await db_session.commit()
    await db_session.refresh(spy_nation)
    await db_session.refresh(target_nation)

    prov = Province(name="Moscow", nation_id=target_nation.id)
    db_session.add(prov)
    await db_session.commit()
    await db_session.refresh(prov)

    design = await create_unit_design(db_session, target_nation.id, "T-90", "tanks", {})

    form = MilitaryFormation(
        nation_id=target_nation.id,
        province_id=prov.id,
        design_id=design.id,
        quantity=10,
        morale=0.9,
    )
    db_session.add(form)

    # Money for spy nation
    money = ResourceLedger(nation_id=spy_nation.id, resource_type="money", balance=20000.0)
    db_session.add(money)
    await db_session.commit()

    # Initial viewing: Fog of war active (no intel)
    forces_initial = await get_visible_forces(db_session, spy_nation.id, target_nation.id, current_turn=1)
    assert forces_initial["fog_of_war_active"] is True
    assert forces_initial["formations"][0]["category"] == "CLASSIFIED"

    # Conduct spy mission
    await conduct_spy_mission(db_session, spy_nation.id, target_nation.id, current_turn=1)

    # Partial intel (level 0.5)
    forces_spied = await get_visible_forces(db_session, spy_nation.id, target_nation.id, current_turn=1)
    assert forces_spied["intel_level"] == 0.5
    assert forces_spied["formations"][0]["category"] == "tanks"
    assert forces_spied["formations"][0]["quantity_estimate"] == 10

    # Conduct second spy mission -> full intel (level 1.0)
    await conduct_spy_mission(db_session, spy_nation.id, target_nation.id, current_turn=1)
    forces_full = await get_visible_forces(db_session, spy_nation.id, target_nation.id, current_turn=1)
    assert forces_full["intel_level"] == 1.0
    assert forces_full["formations"][0]["design_name"] == "T-90"
