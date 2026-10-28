import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.db.models import Nation, UnitDesign, NationTech
from sylus.services.military import (
    calculate_design_stats,
    check_nation_researched_components,
    create_unit_design,
    get_military_config,
)

def test_military_config_loaded():
    cfg = get_military_config()
    assert "categories" in cfg
    assert "components" in cfg
    assert "fighters" in cfg["categories"]
    assert "tanks" in cfg["categories"]

def test_stat_calculator_fighter():
    components = {
        "chassis": "light_chassis",
        "engine": "turbojet_engine",
        "primary_weapon": "air_superiority_cannon",
        "countermeasures": "flare_chaff",
    }
    res = calculate_design_stats("fighters", components)

    assert "stats" in res
    assert "production_cost" in res
    assert "upkeep" in res
    assert "build_time" in res

    stats = res["stats"]
    assert stats["attack"] > 60  # Base 60 + weapon 45
    assert stats["speed"] > 800  # Base 800 + engine 250 + chassis 10 + cannon 20
    assert stats["stealth"] > 0
    assert stats["reliability"] <= 0.99
    assert res["build_time"] >= 1

def test_stat_calculator_tank():
    components = {
        "chassis": "heavy_chassis",
        "armor": "composite_armor",
        "primary_weapon": "smoothbore_cannon",
    }
    res = calculate_design_stats("tanks", components)
    stats = res["stats"]

    assert stats["defense"] >= 90 + 40 + 55  # Base + heavy chassis + composite armor
    assert stats["attack"] >= 85 + 75  # Base + smoothbore cannon
    assert res["production_cost"]["steel"] > 0

@pytest.mark.asyncio
async def test_check_research_and_create_design(db_session: AsyncSession):
    nation = Nation(name="Ares Empire", discord_user_id=888111, leader_name="General Ares")
    db_session.add(nation)
    await db_session.commit()
    await db_session.refresh(nation)

    components = {
        "chassis": "light_chassis",
        "primary_weapon": "assault_rifles",
    }

    # Should fail initially because tech mil_basic_infantry is not unlocked
    is_valid, missing = await check_nation_researched_components(db_session, nation.id, components)
    assert not is_valid
    assert "mil_basic_infantry" in missing

    with pytest.raises(ValueError, match="lacks required tech"):
        await create_unit_design(db_session, nation.id, "Falcon-I", "infantry", components)

    # Unlock required technology
    db_session.add(NationTech(nation_id=nation.id, tech_id="mil_basic_infantry"))
    await db_session.commit()

    # Should succeed now
    is_valid, missing = await check_nation_researched_components(db_session, nation.id, components)
    assert is_valid
    assert len(missing) == 0

    design = await create_unit_design(db_session, nation.id, "Falcon-I", "infantry", components)
    assert design.id is not None
    assert design.name == "Falcon-I"
    assert design.category == "infantry"
    assert design.stats["attack"] > 0
