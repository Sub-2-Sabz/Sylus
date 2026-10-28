import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from sylus.db.models import GlobalState, Nation, Province, ResourceLedger, Building, ResourceMarketIndex
from sylus.services.nation import create_nation, set_policy, build_structure, upgrade_structure, demolish_structure
from sylus.engine.economy import process_economy_turn
from sylus.bot.cogs.nation import NationCog


@pytest.mark.asyncio
async def test_nation_creation_and_one_per_user(async_engine):
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    # Setup province
    async with session_factory() as session:
        p = Province(id=1, name="Capitalia", terrain="plains")
        session.add(p)
        await session.commit()

    # Create nation
    async with session_factory() as session:
        n = await create_nation(
            session=session,
            discord_user_id=1001,
            name="Republic of Test",
            leader_name="Leader One",
            capital_province_id=1,
            color="#FF0000",
            government_type="republic",
            starting_policy="free_market",
        )
        assert n.id is not None
        assert n.name == "Republic of Test"
        assert n.active_policies.get("free_market") is True

    # Try creating second nation for same user (should fail)
    async with session_factory() as session:
        p2 = Province(id=2, name="Secondia", terrain="plains")
        session.add(p2)
        await session.commit()

        with pytest.raises(ValueError, match="already own a nation"):
            await create_nation(
                session=session,
                discord_user_id=1001,
                name="Second Nation",
                leader_name="Leader Two",
                capital_province_id=2,
            )


@pytest.mark.asyncio
async def test_building_construction_and_slot_caps(async_engine):
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        p = Province(id=10, name="Industrial Region", terrain="forest", slot_cap=2)
        session.add(p)
        await session.commit()

        n = await create_nation(
            session=session,
            discord_user_id=2002,
            name="Industry Nation",
            leader_name="Boss",
            capital_province_id=10,
        )

    # Build Sawmill (slot cost 1)
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 2002))).scalar_one()
        b = await build_structure(session, n_res, 10, "sawmill")
        assert b.turns_remaining == 1

    # Build second Sawmill (slot cost 1, max cap reached)
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 2002))).scalar_one()
        b2 = await build_structure(session, n_res, 10, "sawmill")
        assert b2.turns_remaining == 1

    # Attempt third Sawmill (exceeds slot cap)
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 2002))).scalar_one()
        with pytest.raises(ValueError, match="Not enough building slots"):
            await build_structure(session, n_res, 10, "sawmill")


@pytest.mark.asyncio
async def test_economy_production_laffer_and_spoilage(async_engine):
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        p = Province(id=20, name="Woodland", terrain="forest", slot_cap=5)
        session.add(p)
        await session.commit()

        n = await create_nation(
            session=session,
            discord_user_id=3003,
            name="Timberland",
            leader_name="Forester",
            capital_province_id=20,
        )

    # Build Sawmill
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 3003))).scalar_one()
        await build_structure(session, n_res, 20, "sawmill")

    # Turn 1: Advances building construction
    async with session_factory() as session:
        await process_economy_turn(session)
        await session.commit()

    # Turn 2: Sawmill produces wood
    async with session_factory() as session:
        await process_economy_turn(session)
        await session.commit()

    # Check wood balance grew
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 3003))).scalar_one()
        wood_ledger = (
            await session.execute(
                select(ResourceLedger).where(
                    ResourceLedger.nation_id == n_res.id,
                    ResourceLedger.resource_type == "wood",
                )
            )
        ).scalar_one()
        assert wood_ledger.balance > 500.0  # Starting 500 + output


@pytest.mark.asyncio
async def test_policy_toggle_and_cooldown(async_engine):
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        p = Province(id=30, name="Politicus", terrain="plains")
        session.add(p)
        await session.commit()

        n = await create_nation(
            session=session,
            discord_user_id=4004,
            name="Policy State",
            leader_name="Diplomat",
            capital_province_id=30,
        )

    # Adopt state_planned
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 4004))).scalar_one()
        msg = await set_policy(session, n_res, "state_planned", enable=True)
        assert "activated" in msg

    # Immediate second toggle should fail due to cooldown
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 4004))).scalar_one()
        with pytest.raises(ValueError, match="cooldown"):
            await set_policy(session, n_res, "state_planned", enable=False)


@pytest.mark.asyncio
async def test_building_upgrade_and_demolition(async_engine):
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        p = Province(id=40, name="Metro", terrain="plains")
        session.add(p)
        await session.commit()

        n = await create_nation(
            session=session,
            discord_user_id=5005,
            name="Upgrade State",
            leader_name="Builder",
            capital_province_id=40,
        )
        b = await build_structure(session, n, 40, "bank")
        b_id = b.id

    # Finish construction (2 turns required for bank)
    async with session_factory() as session:
        await process_economy_turn(session)
        await process_economy_turn(session)
        await session.commit()

    # Upgrade building
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 5005))).scalar_one()
        upgraded_b = await upgrade_structure(session, n_res, b_id)
        assert upgraded_b.level == 2

    # Demolish building
    async with session_factory() as session:
        n_res = (await session.execute(select(Nation).where(Nation.discord_user_id == 5005))).scalar_one()
        msg = await demolish_structure(session, n_res, b_id)
        assert "Demolished" in msg
