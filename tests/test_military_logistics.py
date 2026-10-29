import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select

from sylus.db.models import (
    Nation, Province, Building, UnitDesign, ResourceLedger,
    MilitaryProductionQueue, MilitaryFormation, NationIntel, GlobalState
)
from sylus.services.military_logistics import (
    enqueue_unit_production,
    list_production_queue,
    cancel_production_queue,
    train_soldiers,
    process_military_turn,
    resupply_formations,
    spy_on_nation,
    get_visible_nation_forces,
)
from sylus.bot.cogs.military import MilitaryCog


@pytest.fixture
async def setup_military_db(db_session):
    now_state = GlobalState(id=1, turn_number=1)
    db_session.add(now_state)

    nat1 = Nation(
        name="Alpha Republic",
        discord_user_id=111,
        soldiers=1000,
        unemployed=2000,
        workers=5000,
    )
    nat2 = Nation(
        name="Beta Kingdom",
        discord_user_id=222,
        soldiers=500,
        unemployed=1000,
        workers=3000,
    )
    db_session.add_all([nat1, nat2])
    await db_session.commit()
    await db_session.refresh(nat1)
    await db_session.refresh(nat2)

    prov1 = Province(name="Alpha Capital", nation_id=nat1.id, is_capital=True)
    prov2 = Province(name="Beta Capital", nation_id=nat2.id, is_capital=True)
    db_session.add_all([prov1, prov2])
    await db_session.commit()
    await db_session.refresh(prov1)
    await db_session.refresh(prov2)

    # Add facilities
    fac1 = Building(province_id=prov1.id, nation_id=nat1.id, building_type="factory", level=2, turns_remaining=0)
    db_session.add(fac1)

    # Add resource ledgers
    ledgers = [
        ResourceLedger(nation_id=nat1.id, resource_type="money", balance=100000.0),
        ResourceLedger(nation_id=nat1.id, resource_type="steel", balance=500.0),
        ResourceLedger(nation_id=nat1.id, resource_type="munitions", balance=500.0),
        ResourceLedger(nation_id=nat1.id, resource_type="gasoline", balance=500.0),
        ResourceLedger(nation_id=nat2.id, resource_type="money", balance=50000.0),
    ]
    db_session.add_all(ledgers)
    await db_session.commit()

    # Add Unit Design
    design = UnitDesign(
        nation_id=nat1.id,
        name="Titan Tank-1",
        category="tanks",
        components={},
        stats={"attack": 85, "defense": 90, "fuel_use": 10, "crew": 4},
        production_cost={"money": 1000, "steel": 20, "munitions": 10},
        upkeep={"money": 100},
        build_time=1,
    )
    db_session.add(design)
    await db_session.commit()
    await db_session.refresh(design)

    return nat1, nat2, prov1, prov2, design


@pytest.mark.asyncio
async def test_train_soldiers(db_session, setup_military_db):
    nat1, nat2, prov1, prov2, design = setup_military_db

    initial_soldiers = nat1.soldiers
    initial_unemployed = nat1.unemployed

    success, msg = await train_soldiers(db_session, nat1.id, 100)
    assert success is True
    assert nat1.soldiers == initial_soldiers + 100
    assert nat1.unemployed == initial_unemployed - 100


@pytest.mark.asyncio
async def test_enqueue_and_cancel_production(db_session, setup_military_db):
    nat1, nat2, prov1, prov2, design = setup_military_db

    # Enqueue production batch
    queue_item = await enqueue_unit_production(db_session, nat1.id, prov1.id, design.id, quantity=2)
    assert queue_item.id is not None
    assert queue_item.quantity == 2

    items = await list_production_queue(db_session, nat1.id)
    assert len(items) == 1

    # Cancel production
    cancelled = await cancel_production_queue(db_session, nat1.id, queue_item.id)
    assert cancelled is True

    items_after = await list_production_queue(db_session, nat1.id)
    assert len(items_after) == 0


@pytest.mark.asyncio
async def test_capacity_limit_enforcement(db_session, setup_military_db):
    nat1, nat2, prov1, prov2, design = setup_military_db

    # Fac1 level 2 factory = capacity 10. Attempting to enqueue 15 units should fail.
    with pytest.raises(ValueError, match="Exceeds factory capacity limit"):
        await enqueue_unit_production(db_session, nat1.id, prov1.id, design.id, quantity=15)


@pytest.mark.asyncio
async def test_process_military_turn_and_resupply(db_session, setup_military_db):
    nat1, nat2, prov1, prov2, design = setup_military_db

    # Enqueue production batch
    await enqueue_unit_production(db_session, nat1.id, prov1.id, design.id, quantity=1)

    # Process turn (should complete queue item into MilitaryFormation)
    summary = await process_military_turn(db_session)
    assert summary["completed_units"] == 1

    # Check formation was created
    stmt = select(MilitaryFormation).where(MilitaryFormation.nation_id == nat1.id)
    res = await db_session.execute(stmt)
    formations = res.scalars().all()
    assert len(formations) == 1
    assert formations[0].quantity == 1

    # Test resupply
    formations[0].fuel_supply = 0.5
    formations[0].ammo_supply = 0.5
    await db_session.commit()

    ok, msg = await resupply_formations(db_session, nat1.id)
    assert ok is True
    assert formations[0].fuel_supply == 1.0
    assert formations[0].ammo_supply == 1.0


@pytest.mark.asyncio
async def test_fog_of_war_and_espionage(db_session, setup_military_db):
    nat1, nat2, prov1, prov2, design = setup_military_db

    # Create formation for nat1
    formation = MilitaryFormation(
        nation_id=nat1.id,
        province_id=prov1.id,
        design_id=design.id,
        quantity=20,
        morale=100.0,
        experience=25.0,
        fuel_supply=1.0,
        ammo_supply=1.0,
    )
    db_session.add(formation)
    await db_session.commit()

    # Nat2 inspects Nat1 without intel (Fog of war active)
    intel_lvl, forces = await get_visible_nation_forces(db_session, viewer_nation_id=nat2.id, target_nation_id=nat1.id)
    assert intel_lvl == 0
    assert len(forces) == 1
    assert forces[0]["fog_of_war"] is True
    assert forces[0]["design_name"] == "[Hidden by Fog of War]"

    # Nat2 executes spy mission against Nat1
    ok, msg = await spy_on_nation(db_session, spy_nation_id=nat2.id, target_nation_id=nat1.id)
    assert ok is True

    # Inspect again with intel
    intel_lvl_2, forces_2 = await get_visible_nation_forces(db_session, viewer_nation_id=nat2.id, target_nation_id=nat1.id)
    assert intel_lvl_2 == 2
    assert forces_2[0]["fog_of_war"] is False
    assert forces_2[0]["design_name"] == "Titan Tank-1"
    assert forces_2[0]["quantity"] == 20


@pytest.mark.asyncio
async def test_military_cog_slash_commands(db_session, setup_military_db):
    nat1, nat2, prov1, prov2, design = setup_military_db

    bot = MagicMock()
    cog = MilitaryCog(bot)

    # Test /military build
    ctx = AsyncMock()
    ctx.author.id = nat1.discord_user_id
    await cog.build_unit.callback(cog, ctx, province_name="Alpha Capital", design_id=design.id, quantity=1)
    ctx.respond.assert_called_once()

    # Test /military queue
    ctx_q = AsyncMock()
    ctx_q.author.id = nat1.discord_user_id
    await cog.view_queue.callback(cog, ctx_q)
    ctx_q.respond.assert_called_once()

    # Test /military train
    ctx_t = AsyncMock()
    ctx_t.author.id = nat1.discord_user_id
    await cog.train_manpower.callback(cog, ctx_t, quantity=50)
    ctx_t.respond.assert_called_once()
