import pytest
from sqlalchemy import select
from sylus.db.models import Nation, Province, ResourceLedger, War, WarLog, MilitaryFormation, UnitDesign
from sylus.services.war_modifier import (
    calculate_terrain_modifier,
    calculate_weather_modifier,
    calculate_season_modifier,
    calculate_supply_modifier,
    calculate_morale_modifier,
    calculate_fatigue_modifier,
    calculate_experience_modifier,
    calculate_tech_gap_modifier,
    calculate_air_superiority_modifier,
    calculate_naval_control_modifier,
    calculate_radar_modifier,
    calculate_fortifications_modifier,
    calculate_home_field_modifier,
    calculate_war_support_modifier,
    evaluate_combat_modifiers,
)
from sylus.services.war import declare_war, process_war_turn, execute_war_action
from sylus.engine.turn import process_single_turn


def test_independent_modifiers():
    # 1. Terrain
    assert calculate_terrain_modifier("ground_attack", "mountains", "defender") == 1.25
    assert calculate_terrain_modifier("ground_attack", "mountains", "attacker") == 0.85
    assert calculate_terrain_modifier("ground_attack", "jungle", "attacker") == 0.80

    # 2. Weather
    assert calculate_weather_modifier("air_strike", "clear") == 1.0
    assert calculate_weather_modifier("air_strike", "storm") == 0.0  # Grounded
    assert calculate_weather_modifier("ground_attack", "mud") == 0.70

    # 3. Season
    assert calculate_season_modifier("ground_attack", "spring", "plains") == 1.0
    assert calculate_season_modifier("ground_attack", "winter", "arctic") == 0.80

    # 4. Supply
    assert calculate_supply_modifier(1.0) == 1.0
    assert calculate_supply_modifier(0.0) == 0.50

    # 5. Morale
    assert calculate_morale_modifier(100.0) == 1.0
    assert calculate_morale_modifier(50.0) == 0.75

    # 6. Fatigue
    assert calculate_fatigue_modifier(0.0) == 1.0
    assert calculate_fatigue_modifier(0.5) == 0.75

    # 7. Experience
    assert calculate_experience_modifier(10.0) == 1.0
    assert calculate_experience_modifier(60.0) == 1.10

    # 8. Tech gap
    assert calculate_tech_gap_modifier(5, 2, "attacker") == 1.15
    assert calculate_tech_gap_modifier(2, 5, "attacker") == 0.85

    # 9. Air superiority
    assert calculate_air_superiority_modifier(100.0, 0.0, "attacker") == 1.25
    assert calculate_air_superiority_modifier(0.0, 100.0, "attacker") == 0.75

    # 10. Naval control
    assert calculate_naval_control_modifier(100.0, 0.0, "attacker") == 1.25

    # 11. Radar
    assert calculate_radar_modifier(True, "defender") == 1.15
    assert calculate_radar_modifier(False, "defender") == 1.0

    # 12. Fortifications
    assert calculate_fortifications_modifier(3, "defender") == 1.20
    assert calculate_fortifications_modifier(3, "attacker") == 1.0

    # 13. Home field
    assert calculate_home_field_modifier(True, "defender") == 1.15
    assert calculate_home_field_modifier(False, "defender") == 1.0

    # 14. War support
    assert calculate_war_support_modifier(0.80) == 1.09
    assert calculate_war_support_modifier(0.20) == 0.91


def test_evaluate_combat_modifiers_combination():
    res = evaluate_combat_modifiers(
        action_type="ground_attack",
        terrain="mountains",
        weather="clear",
        season="spring",
        role="defender",
        supply_level=1.0,
        morale=100.0,
        fatigue=0.0,
        experience=10.0,
        infrastructure_level=2,
        is_home=True,
    )
    assert res["breakdown"]["terrain"] == 1.25
    assert res["breakdown"]["fortifications"] == 1.10
    assert res["breakdown"]["home_field"] == 1.15
    assert res["total_multiplier"] > 1.30


@pytest.mark.asyncio
async def test_war_declaration_rules(db_session):
    # Setup test nations
    n1 = Nation(name="Sparta", discord_user_id=1001, score=100.0, happiness=0.80, war_support=0.70)
    n2 = Nation(name="Athens", discord_user_id=1002, score=100.0, happiness=0.80, war_support=0.70)
    n3 = Nation(name="Persia", discord_user_id=1003, score=500.0, happiness=0.80, war_support=0.70)  # High score diff
    db_session.add_all([n1, n2, n3])
    await db_session.commit()

    # 1. Unprovoked war declaration (cb="none") -> penalty
    war = await declare_war(db_session, n1.id, n2.id, casus_belli="none", current_turn=1)
    assert war.status == "active"
    assert war.attacker_ap == 12
    assert war.defender_ap == 12
    assert n1.happiness < 0.80  # Penalty applied

    # 2. Duplicate active war -> raises error
    with pytest.raises(ValueError, match="An active war already exists"):
        await declare_war(db_session, n1.id, n2.id, casus_belli="border_dispute", current_turn=1)

    # 3. Self war declaration -> raises error
    with pytest.raises(ValueError, match="Cannot declare war on oneself"):
        await declare_war(db_session, n1.id, n1.id)

    # 4. Out of range score declaration -> raises error
    with pytest.raises(ValueError, match="outside allowed war range"):
        await declare_war(db_session, n1.id, n3.id)


@pytest.mark.asyncio
async def test_process_war_turn_and_ap_refill(db_session):
    n1 = Nation(name="Rome", discord_user_id=2001, score=100.0)
    n2 = Nation(name="Carthage", discord_user_id=2002, score=100.0)
    db_session.add_all([n1, n2])
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="territorial_claim", current_turn=1)
    war.attacker_ap = 5
    war.attacker_fatigue = 0.30
    await db_session.commit()

    summary = await process_war_turn(db_session, current_turn=2)
    await db_session.commit()
    assert summary["active_wars_refilled"] == 1

    await db_session.refresh(war)
    assert war.attacker_ap == 12  # Refilled
    assert war.attacker_fatigue < 0.30  # Decayed


@pytest.mark.asyncio
async def test_execute_war_actions_and_victory_tiers(db_session):
    n1 = Nation(name="Valyria", discord_user_id=3001, score=100.0)
    n2 = Nation(name="Ghiscar", discord_user_id=3002, score=100.0)
    db_session.add_all([n1, n2])
    await db_session.commit()

    p2 = Province(name="Old Ghis", nation_id=n2.id, terrain="plains", infrastructure=1)
    db_session.add(p2)
    await db_session.commit()

    r2 = ResourceLedger(nation_id=n2.id, resource_type="money", balance=1000.0)
    db_session.add(r2)
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="border_dispute", current_turn=1)

    # Execute Ground Attack with seeded high positive roll -> Immense Triumph
    log1 = await execute_war_action(
        db_session, war_id=war.id, actor_id=n1.id, action_type="ground_attack",
        province_id=p2.id, current_turn=1, seed=50.0
    )
    assert log1.victory_tier == "Immense Triumph"
    assert log1.roll_diff >= 40.0
    assert "money" in log1.loot_resources

    # Execute Air Strike with seeded low roll -> Failure
    log2 = await execute_war_action(
        db_session, war_id=war.id, actor_id=n1.id, action_type="air_strike",
        province_id=p2.id, current_turn=1, seed=-50.0
    )
    assert log2.victory_tier == "Failure"

    # Ceasefire flow
    cf1 = await execute_war_action(db_session, war_id=war.id, actor_id=n1.id, action_type="ceasefire_offer", current_turn=1)
    assert cf1.victory_tier == "Ceasefire Offered"

    cf2 = await execute_war_action(db_session, war_id=war.id, actor_id=n2.id, action_type="ceasefire_offer", current_turn=1)
    assert cf2.victory_tier == "Ceasefire Accepted"

    await db_session.refresh(war)
    assert war.status == "beige"
    assert war.beige_until_turn == 13


@pytest.mark.asyncio
async def test_turn_engine_war_integration(db_session):
    n1 = Nation(name="Gondor", discord_user_id=4001, score=100.0)
    n2 = Nation(name="Mordor", discord_user_id=4002, score=100.0)
    db_session.add_all([n1, n2])
    await db_session.commit()

    war = await declare_war(db_session, n1.id, n2.id, casus_belli="retaliation", current_turn=1)
    war.attacker_ap = 2
    await db_session.commit()

    turn_res = await process_single_turn(db_session, force=True)
    assert turn_res is not None
    assert turn_res.executed is True
    assert "War & Conflicts" in [f["name"] for f in turn_res.summary_embed_dict["fields"]]

    await db_session.refresh(war)
    assert war.attacker_ap == 12
