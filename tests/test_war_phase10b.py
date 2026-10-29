import pytest
from sqlalchemy import select
from sylus.db.models import (
    Nation, Province, ResourceLedger, Building, DisasterZone, NationTech, UnitDesign, MilitaryFormation
)
from sylus.db.war_models import War, WarLog, ProvinceOccupation, PortBlockade, PeaceTreaty
from sylus.services.war import declare_war, execute_war_action
from sylus.services.war_occupation import (
    advance_occupation, apply_blockade, process_occupation_and_blockades_turn,
    check_war_exhaustion, trigger_forced_surrender
)
from sylus.services.war_nukes import check_nuclear_eligibility, execute_nuclear_strike
from sylus.services.peace_treaty import create_peace_treaty, accept_peace_treaty, process_peace_treaties_turn
from sylus.map.renderer import MapRenderer


@pytest.mark.asyncio
async def test_occupation_progress_and_insurgency(db_session):
    n1 = Nation(name="Alpha", discord_user_id=8001, score=100.0)
    n2 = Nation(name="Beta", discord_user_id=8002, score=100.0)
    db_session.add_all([n1, n2])
    await db_session.commit()

    p2 = Province(name="Frontier", nation_id=n2.id, terrain="plains", is_capital=False)
    db_session.add(p2)
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="border_dispute", current_turn=1)

    # Ground attack advance occupation
    occ, cap_captured = await advance_occupation(db_session, war.id, n1.id, p2.id, "Immense Triumph", current_turn=1)
    assert occ.occupation_progress == 50.0
    assert occ.is_fully_occupied is False
    assert cap_captured is False

    # Second ground attack advances to 100%
    occ2, cap_captured2 = await advance_occupation(db_session, war.id, n1.id, p2.id, "Immense Triumph", current_turn=1)
    assert occ2.occupation_progress == 100.0
    assert occ2.is_fully_occupied is True

    # Test insurgency growth per turn without garrison
    sum1 = await process_occupation_and_blockades_turn(db_session, current_turn=2)
    await db_session.refresh(occ2)
    assert occ2.insurgency_level == 5.0

    # Add garrison to decay insurgency
    design = UnitDesign(nation_id=n1.id, name="Infantry", category="militia", components={}, stats={}, production_cost={}, upkeep={})
    db_session.add(design)
    await db_session.commit()

    garrison = MilitaryFormation(nation_id=n1.id, province_id=p2.id, design_id=design.id, quantity=100)
    db_session.add(garrison)
    await db_session.commit()

    sum2 = await process_occupation_and_blockades_turn(db_session, current_turn=3)
    await db_session.refresh(occ2)
    assert occ2.insurgency_level == 0.0  # Decayed by 10.0


@pytest.mark.asyncio
async def test_port_blockade_lifecycle(db_session):
    n1 = Nation(name="NavalPower", discord_user_id=8101, score=100.0)
    n2 = Nation(name="CoastalTarget", discord_user_id=8102, score=100.0)
    db_session.add_all([n1, n2])
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="territorial_claim", current_turn=1)

    # Execute blockade action
    log = await execute_war_action(db_session, war.id, n1.id, "blockade", current_turn=1)
    assert log.action_type == "blockade"

    blk_stmt = select(PortBlockade).where(PortBlockade.war_id == war.id)
    blk = (await db_session.execute(blk_stmt)).scalar_one_or_none()
    assert blk is not None
    assert blk.turns_remaining == 6

    # Fast forward turn countdown
    for t in range(2, 8):
        res = await process_occupation_and_blockades_turn(db_session, current_turn=t)

    blk_after = (await db_session.execute(blk_stmt)).scalar_one_or_none()
    assert blk_after is None  # Expired and deleted


@pytest.mark.asyncio
async def test_capital_capture_and_forced_surrender(db_session):
    n1 = Nation(name="Invader", discord_user_id=8201, score=100.0)
    n2 = Nation(name="DefenderCap", discord_user_id=8202, score=100.0, war_support=0.80)
    db_session.add_all([n1, n2])
    await db_session.commit()

    cap_prov = Province(name="CapitalCity", nation_id=n2.id, terrain="urban", is_capital=True)
    db_session.add(cap_prov)
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="aggressor", current_turn=1)

    # Capture capital province
    await advance_occupation(db_session, war.id, n1.id, cap_prov.id, "Immense Triumph", current_turn=1)
    await advance_occupation(db_session, war.id, n1.id, cap_prov.id, "Immense Triumph", current_turn=1)

    await db_session.refresh(war)
    assert war.status == "beige"  # Forced surrender triggered
    assert war.beige_until_turn == 13


@pytest.mark.asyncio
async def test_war_exhaustion_surrender(db_session):
    n1 = Nation(name="AttackerE", discord_user_id=8301, score=100.0, war_support=0.80)
    n2 = Nation(name="ExhaustedDef", discord_user_id=8302, score=100.0, war_support=0.02)  # Below 0.05
    db_session.add_all([n1, n2])
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="retaliation", current_turn=1)

    surrendered_id = await check_war_exhaustion(db_session, war.id, current_turn=1)
    assert surrendered_id == n2.id

    await db_session.refresh(war)
    assert war.status == "beige"


@pytest.mark.asyncio
async def test_peace_treaty_proposal_acceptance_and_enforcement(db_session):
    n1 = Nation(name="Victorious", discord_user_id=8401, score=100.0, soldiers=1000)
    n2 = Nation(name="Defeated", discord_user_id=8402, score=100.0, soldiers=800)
    db_session.add_all([n1, n2])
    await db_session.commit()

    p2 = Province(name="CededLand", nation_id=n2.id, terrain="plains")
    db_session.add(p2)
    await db_session.commit()

    r2 = ResourceLedger(nation_id=n2.id, resource_type="money", balance=10000.0)
    db_session.add(r2)
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="territorial_claim", current_turn=1)

    treaty = await create_peace_treaty(
        db_session, war.id, n1.id,
        reparations_per_turn=500.0,
        territory_transfers=[p2.id],
        demilitarization_max_soldiers=300,
        current_turn=1,
    )
    assert treaty.status == "pending"

    # Accept peace treaty
    accepted_tr = await accept_peace_treaty(db_session, treaty.id, n2.id, current_turn=1)
    assert accepted_tr.status == "accepted"

    await db_session.refresh(p2)
    assert p2.nation_id == n1.id  # Immediate territory transfer!

    await db_session.refresh(war)
    assert war.status == "beige"  # War concluded to beige

    # Process per-turn peace obligations
    peace_summary = await process_peace_treaties_turn(db_session, current_turn=2)
    assert peace_summary["reparations_executed"] == 1
    assert peace_summary["demilitarizations_enforced"] == 1

    await db_session.refresh(r2)
    assert r2.balance == 9500.0  # 500 transferred

    await db_session.refresh(n2)
    assert n2.soldiers == 300  # Demilitarized to cap


@pytest.mark.asyncio
async def test_nuclear_strike_eligibility_interception_and_devastation(db_session):
    n1 = Nation(name="NuclearState", discord_user_id=8501, score=100.0, happiness=0.80, war_support=0.70)
    n2 = Nation(name="TargetState", discord_user_id=8502, score=100.0, happiness=0.80, war_support=0.70)
    db_session.add_all([n1, n2])
    await db_session.commit()

    target_prov = Province(name="Metropolis", nation_id=n2.id, terrain="urban", population=50000, infrastructure=5)
    db_session.add(target_prov)
    await db_session.commit()

    bld = Building(province_id=target_prov.id, nation_id=n2.id, building_type="steel_mill", level=3)
    db_session.add(bld)
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="aggressor", current_turn=1)

    # 1. Eligibility check initially fails (missing tech/resources/design)
    eligible, reason = await check_nuclear_eligibility(db_session, n1.id)
    assert eligible is False

    # Grant tech, resources, and missile design
    db_session.add(NationTech(nation_id=n1.id, tech_id="nuclear_weapons"))
    db_session.add(ResourceLedger(nation_id=n1.id, resource_type="uranium", balance=100.0))
    db_session.add(ResourceLedger(nation_id=n1.id, resource_type="plutonium", balance=50.0))
    db_session.add(UnitDesign(nation_id=n1.id, name="ICBM-1", category="missiles", components={}, stats={}, production_cost={}, upkeep={}))
    await db_session.commit()

    eligible_now, _ = await check_nuclear_eligibility(db_session, n1.id)
    assert eligible_now is True

    # 2. Execute strike with low seed -> Detonation
    nuke_log = await execute_nuclear_strike(db_session, war.id, n1.id, target_prov.id, current_turn=1, seed=0.99)
    assert nuke_log.victory_tier == "Immense Triumph"
    assert "NUCLEAR DETONATION" in nuke_log.summary

    await db_session.refresh(target_prov)
    assert target_prov.population < 50000
    assert target_prov.infrastructure == 1

    # Check destroyed buildings
    bld_check = (await db_session.execute(select(Building).where(Building.province_id == target_prov.id))).scalars().all()
    assert len(bld_check) == 0  # Wiped out

    # Check fallout zone spawned
    dz_check = (await db_session.execute(select(DisasterZone).where(DisasterZone.province_id == target_prov.id))).scalar_one_or_none()
    assert dz_check is not None
    assert dz_check.disaster_type == "fallout"


def test_war_front_map_rendering():
    renderer = MapRenderer()
    # Render with occupied_provinces dict in mode="war"
    occupied_provinces = {1: 100, 2: 100}
    stream = renderer.render_map(
        occupied_provinces=occupied_provinces,
        mode="war",
        legend_title="War Front World Map"
    )
    data = stream.getvalue()
    assert len(data) > 0
    assert data.startswith(b"\x89PNG")
