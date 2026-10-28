import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.db.models import Nation, Province, ResourceLedger, NationTech, ResearchQueue, TechLicense
from sylus.services.nation import create_nation
from sylus.services.research import (
    get_all_tech_definitions,
    format_progress_bar,
    get_available_techs,
    queue_technology,
    cancel_research,
    create_tech_license,
    process_research_turn,
)


@pytest.mark.asyncio
async def test_all_tech_definitions_loading():
    techs = get_all_tech_definitions()
    assert len(techs) > 0
    # Check military components
    assert "mil_engines_1" in techs
    assert "mil_engines_2" in techs
    assert "mil_radar_1" in techs
    assert techs["mil_engines_1"]["tree"] == "military"
    # Check other trees
    assert "eco_banking_1" in techs
    assert "com_health_1" in techs
    assert "ind_auto_1" in techs
    assert "energy_grid_1" in techs
    assert "esp_intel_1" in techs
    assert "space_rocket_1" in techs


def test_progress_bar_formatting():
    bar_0 = format_progress_bar(0, 100)
    assert "0%" in bar_0
    bar_50 = format_progress_bar(50, 100)
    assert "50%" in bar_50
    bar_100 = format_progress_bar(100, 100)
    assert "100%" in bar_100


@pytest.mark.asyncio
async def test_research_queue_and_prerequisites(db_session: AsyncSession):
    # Setup starting province and nation
    p = Province(id=1, name="Alpha", terrain="plains", is_capital=True)
    db_session.add(p)
    await db_session.commit()

    nat = await create_nation(
        db_session,
        discord_user_id=12345,
        name="TechNation",
        leader_name="Scientist",
        capital_province_id=1,
    )

    # Level 1 engines should be queueable (no prereqs)
    q1 = await queue_technology(db_session, nat, "mil_engines_1")
    assert q1.tech_id == "mil_engines_1"
    assert q1.queue_position == 1

    # Level 2 engines should fail due to missing level 1
    with pytest.raises(ValueError, match="Missing prerequisites"):
        await queue_technology(db_session, nat, "mil_engines_2")

    # Duplicate queuing should fail
    with pytest.raises(ValueError, match="already in the research queue"):
        await queue_technology(db_session, nat, "mil_engines_1")


@pytest.mark.asyncio
async def test_research_cancellation_and_refund(db_session: AsyncSession):
    p = Province(id=2, name="Beta", terrain="plains", is_capital=True)
    db_session.add(p)
    await db_session.commit()

    nat = await create_nation(
        db_session,
        discord_user_id=67890,
        name="CancelNation",
        leader_name="Leader",
        capital_province_id=2,
    )

    q = await queue_technology(db_session, nat, "mil_guns_1")
    # Simulate partial allocation
    q.allocated_rp = 40.0
    await db_session.commit()

    refunded = await cancel_research(db_session, nat, q.id)
    assert refunded == 40.0

    rp_ledger = (
        await db_session.execute(
            select(ResourceLedger).where(
                ResourceLedger.nation_id == nat.id, ResourceLedger.resource_type == "research_points"
            )
        )
    ).scalar_one()

    assert rp_ledger.balance == 40.0


@pytest.mark.asyncio
async def test_research_turn_processing_and_unlock(db_session: AsyncSession):
    p = Province(id=3, name="Gamma", terrain="plains", is_capital=True)
    db_session.add(p)
    await db_session.commit()

    nat = await create_nation(
        db_session,
        discord_user_id=11111,
        name="ProgressNation",
        leader_name="Professor",
        capital_province_id=3,
    )

    q = await queue_technology(db_session, nat, "com_health_1")
    cost = q.target_rp

    # Update existing RP ledger
    rp_ledger = (
        await db_session.execute(
            select(ResourceLedger).where(
                ResourceLedger.nation_id == nat.id, ResourceLedger.resource_type == "research_points"
            )
        )
    ).scalar_one()
    rp_ledger.balance = cost
    await db_session.commit()

    # Process research turn
    res = await process_research_turn(db_session)
    assert res["completed_techs"] == 1

    # Check that tech is now unlocked
    unlocked = (
        await db_session.execute(select(NationTech).where(NationTech.nation_id == nat.id))
    ).scalars().all()
    assert len(unlocked) == 1
    assert unlocked[0].tech_id == "com_health_1"


@pytest.mark.asyncio
async def test_tech_license_creation_and_royalties(db_session: AsyncSession):
    p1 = Province(id=4, name="Delta", terrain="plains", is_capital=True)
    p2 = Province(id=5, name="Epsilon", terrain="plains", is_capital=True)
    db_session.add_all([p1, p2])
    await db_session.commit()

    licensor = await create_nation(
        db_session, discord_user_id=22222, name="LicensorNation", leader_name="L1", capital_province_id=4
    )
    licensee = await create_nation(
        db_session, discord_user_id=33333, name="LicenseeNation", leader_name="L2", capital_province_id=5
    )

    # Unlock tech for licensor
    db_session.add(NationTech(nation_id=licensor.id, tech_id="eco_banking_1"))

    # Update money balances for royalty test
    m_licensor = (
        await db_session.execute(
            select(ResourceLedger).where(
                ResourceLedger.nation_id == licensor.id, ResourceLedger.resource_type == "money"
            )
        )
    ).scalar_one()
    m_licensee = (
        await db_session.execute(
            select(ResourceLedger).where(
                ResourceLedger.nation_id == licensee.id, ResourceLedger.resource_type == "money"
            )
        )
    ).scalar_one()

    m_licensor.balance = 100.0
    m_licensee.balance = 500.0
    await db_session.commit()

    lic = await create_tech_license(db_session, licensor, licensee, "eco_banking_1", royalty_per_turn=50.0)
    assert lic.tech_id == "eco_banking_1"

    # Licensee can now queue tech requiring eco_banking_1 as prereq!
    available = await get_available_techs(db_session, licensee.id, tree_filter="economy")
    b2 = next(t for t in available if t["tech_id"] == "eco_banking_2")
    assert b2["status"] == "AVAILABLE"

    # Run research turn to test royalty payment
    await process_research_turn(db_session)

    m1 = (
        await db_session.execute(
            select(ResourceLedger).where(
                ResourceLedger.nation_id == licensor.id, ResourceLedger.resource_type == "money"
            )
        )
    ).scalar_one()
    m2 = (
        await db_session.execute(
            select(ResourceLedger).where(
                ResourceLedger.nation_id == licensee.id, ResourceLedger.resource_type == "money"
            )
        )
    ).scalar_one()

    assert m1.balance == 150.0
    assert m2.balance == 450.0
