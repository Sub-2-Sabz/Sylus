import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from sylus.db.models import GlobalState, Nation, ResourceLedger, utc_now
from sylus.engine.turn import (
    get_or_create_global_state,
    process_single_turn,
    export_snapshot,
    restore_snapshot,
)
from sylus.engine.scheduler import TurnScheduler
from sylus.cli import fast_forward_turns


@pytest.mark.asyncio
async def test_crash_mid_turn(async_engine):
    """Test that a crash/exception mid-turn rolls back and leaves turn_number unchanged."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    # Initialize state
    async with session_factory() as session:
        state = await get_or_create_global_state(session)
        assert state.turn_number == 1

    # Simulate mid-turn crash within transaction
    async with session_factory() as session:
        try:
            async with session.begin():
                result = await process_single_turn(session, force=True)
                assert result is not None
                assert result.turn_number == 1
                # Inject a mid-turn exception before commit
                raise RuntimeError("Simulated mid-turn crash!")
        except RuntimeError:
            pass

    # Verify state was rolled back to turn 1
    async with session_factory() as session:
        res = await session.execute(select(GlobalState).where(GlobalState.id == 1))
        state = res.scalar_one()
        assert state.turn_number == 1

    # Process turn cleanly now
    async with session_factory() as session:
        result = await process_single_turn(session, force=True)
        await session.commit()
        assert result is not None
        assert result.turn_number == 1

    async with session_factory() as session:
        res = await session.execute(select(GlobalState).where(GlobalState.id == 1))
        state = res.scalar_one()
        assert state.turn_number == 2


@pytest.mark.asyncio
async def test_overlapping_instances(async_engine):
    """Test that two overlapping instances attempting turn N results in only one succeeding via CAS."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        await get_or_create_global_state(session)

    async def run_instance(instance_id: int):
        async with session_factory() as session:
            res = await process_single_turn(session, force=True)
            if res:
                await session.commit()
            return res

    # Run two overlapping instances concurrently
    results = await asyncio.gather(run_instance(1), run_instance(2))

    # Exactly one instance should succeed (executed=True) and one should be None
    executed_results = [r for r in results if r is not None and r.executed]
    assert len(executed_results) == 1
    assert executed_results[0].turn_number == 1

    # Confirm turn number in DB is 2
    async with session_factory() as session:
        res = await session.execute(select(GlobalState).where(GlobalState.id == 1))
        state = res.scalar_one()
        assert state.turn_number == 2


@pytest.mark.asyncio
async def test_5_overdue_turns_on_startup(async_engine):
    """Test catch-up of 5 overdue turns in order on startup."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    # Set next_turn_at to 9.8 hours ago (5 overdue turns at 2h intervals)
    async with session_factory() as session:
        state = await get_or_create_global_state(session)
        state.next_turn_at = utc_now() - timedelta(hours=9, minutes=50)
        state.turn_number = 1
        await session.commit()

    scheduler = TurnScheduler(session_factory=session_factory)
    processed = await scheduler.catch_up_overdue_turns()

    assert processed == 5

    # Check global state turn number advanced to 6
    async with session_factory() as session:
        res = await session.execute(select(GlobalState).where(GlobalState.id == 1))
        state = res.scalar_one()
        assert state.turn_number == 6


@pytest.mark.asyncio
async def test_no_duplicated_turn(async_engine):
    """Test that turns are never duplicated under repeated/concurrent triggers."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        await get_or_create_global_state(session)

    processed_turn_numbers = []

    # Execute 3 sequential turns
    for _ in range(3):
        async with session_factory() as session:
            res = await process_single_turn(session, force=True)
            if res:
                await session.commit()
                processed_turn_numbers.append(res.turn_number)

    # Assert no duplicate turn numbers in processed list
    assert processed_turn_numbers == [1, 2, 3]
    assert len(processed_turn_numbers) == len(set(processed_turn_numbers))


@pytest.mark.asyncio
async def test_export_and_restore_snapshot(async_engine):
    """Test snapshot export and state restoration."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    # Create initial nation and resource
    async with session_factory() as session:
        state = await get_or_create_global_state(session)
        state.turn_number = 42

        nation = Nation(id=10, name="Atlantis", discord_user_id=123456, color="#0000FF")
        session.add(nation)
        await session.commit()

        resource = ResourceLedger(id=100, nation_id=10, resource_type="gold", balance=5000.0)
        session.add(resource)
        await session.commit()

    # Export snapshot
    async with session_factory() as session:
        snapshot = await export_snapshot(session)

    assert snapshot["version"] == 1
    assert len(snapshot["nations"]) == 1
    assert snapshot["nations"][0]["name"] == "Atlantis"

    # Mutate state in DB
    async with session_factory() as session:
        res = await session.execute(select(Nation).where(Nation.id == 10))
        nation = res.scalar_one()
        nation.name = "Corrupted Nation"
        await session.commit()

    # Restore snapshot
    async with session_factory() as session:
        await restore_snapshot(session, snapshot)

    # Verify state restored
    async with session_factory() as session:
        res = await session.execute(select(Nation).where(Nation.id == 10))
        nation = res.scalar_one()
        assert nation.name == "Atlantis"

        res_g = await session.execute(select(GlobalState).where(GlobalState.id == 1))
        state = res_g.scalar_one()
        assert state.turn_number == 42


@pytest.mark.asyncio
async def test_pause_resume_scheduler(async_engine):
    """Test pausing and resuming turn engine."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    # Pause engine
    async with session_factory() as session:
        state = await get_or_create_global_state(session)
        state.is_paused = True
        await session.commit()

    # Turn processing without force should return None
    async with session_factory() as session:
        res = await process_single_turn(session, force=False)
        assert res is None

    # Resume engine
    async with session_factory() as session:
        state = await get_or_create_global_state(session)
        state.is_paused = False
        await session.commit()

    # Turn processing should now succeed
    async with session_factory() as session:
        res = await process_single_turn(session, force=False)
        assert res is not None
        assert res.turn_number == 1


@pytest.mark.asyncio
async def test_cli_fast_forward(async_engine):
    """Test CLI fast-forward N turns function."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        await get_or_create_global_state(session)

    completed = await fast_forward_turns(4)
    assert completed == 4

    async with session_factory() as session:
        res = await session.execute(select(GlobalState).where(GlobalState.id == 1))
        state = res.scalar_one()
        assert state.turn_number == 5
