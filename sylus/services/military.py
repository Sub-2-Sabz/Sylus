import math
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import UnitDesign, NationTech, Nation, utc_now
from sylus.logging import get_logger

logger = get_logger(__name__)


def get_military_config() -> Dict[str, Any]:
    """Loads and returns military configuration dictionary."""
    return config.get("military", {})


def get_category_config(category: str) -> Optional[Dict[str, Any]]:
    """Returns configuration dictionary for a given unit category."""
    mil_cfg = get_military_config()
    return mil_cfg.get("categories", {}).get(category)


def get_component_info(slot: str, comp_key: str) -> Optional[Dict[str, Any]]:
    """Returns component metadata dictionary for a given slot and key."""
    mil_cfg = get_military_config()
    components = mil_cfg.get("components", {})
    if slot in components and comp_key in components[slot]:
        return components[slot][comp_key]
    for group in components.values():
        if isinstance(group, dict) and comp_key in group:
            return group[comp_key]
    return None


def calculate_design_stats(category: str, component_selections: Dict[str, str]) -> Dict[str, Any]:
    """
    Pure stat calculator turning a unit category and component selection into stats.
    Returns calculated stats, production costs, upkeep, and build time.
    """
    cat_cfg = get_category_config(category)
    if not cat_cfg:
        raise ValueError(f"Unknown unit category: {category}")

    base_stats = cat_cfg.get("base_stats", {})
    calc_cfg = get_military_config().get("base_calculator", {})

    # Start with copies of base stats
    attack = float(base_stats.get("attack", 0))
    defense = float(base_stats.get("defense", 0))
    speed = float(base_stats.get("speed", 0))
    unit_range = float(base_stats.get("range", 0))
    fuel_use = float(base_stats.get("fuel_use", 0))
    stealth = float(base_stats.get("stealth", 0))
    detection = float(base_stats.get("detection", 0))
    reliability = float(base_stats.get("reliability", 0.90))
    crew = int(base_stats.get("crew", 0))
    build_time = int(base_stats.get("build_time", 1))

    # Base production costs & upkeep
    production_cost: Dict[str, float] = dict(base_stats.get("production_cost", {}))
    upkeep: Dict[str, float] = dict(base_stats.get("upkeep", {}))

    # Apply component modifiers
    for slot, comp_key in component_selections.items():
        if not comp_key:
            continue
        comp = get_component_info(slot, comp_key)
        if not comp:
            continue

        stat_mods = comp.get("stat_modifiers", {})
        attack += float(stat_mods.get("attack", 0))
        defense += float(stat_mods.get("defense", 0))
        speed += float(stat_mods.get("speed", 0))
        unit_range += float(stat_mods.get("range", 0))
        fuel_use += float(stat_mods.get("fuel_use", 0))
        stealth += float(stat_mods.get("stealth", 0))
        detection += float(stat_mods.get("detection", 0))
        reliability += float(stat_mods.get("reliability", 0))
        crew += int(stat_mods.get("crew", 0))

        cost_mods = comp.get("cost_modifiers", {})
        for res_type, amount in cost_mods.items():
            production_cost[res_type] = production_cost.get(res_type, 0.0) + float(amount)

    # Clamping & boundary rules
    min_rel = float(calc_cfg.get("min_reliability", 0.10))
    max_rel = float(calc_cfg.get("max_reliability", 0.99))

    attack = max(0.0, attack)
    defense = max(0.0, defense)
    speed = max(0.0, speed)
    unit_range = max(0.0, unit_range)
    fuel_use = max(0.0, fuel_use)
    stealth = max(0.0, min(100.0, stealth))
    detection = max(0.0, min(100.0, detection))
    reliability = max(min_rel, min(max_rel, reliability))
    crew = max(0, crew)
    build_time = max(1, build_time)

    # Auto-calculate upkeep money if not specified based on ratio
    upkeep_ratio = float(calc_cfg.get("base_upkeep_ratio", 0.05))
    if "money" in production_cost and "money" not in upkeep:
        upkeep["money"] = round(production_cost["money"] * upkeep_ratio, 2)

    return {
        "stats": {
            "attack": round(attack, 2),
            "defense": round(defense, 2),
            "speed": round(speed, 2),
            "range": round(unit_range, 2),
            "fuel_use": round(fuel_use, 2),
            "stealth": round(stealth, 2),
            "detection": round(detection, 2),
            "reliability": round(reliability, 3),
            "crew": crew,
        },
        "production_cost": {k: round(v, 2) for k, v in production_cost.items() if v > 0},
        "upkeep": {k: round(v, 2) for k, v in upkeep.items() if v > 0},
        "build_time": build_time,
    }


async def check_nation_researched_components(
    session: AsyncSession, nation_id: int, component_selections: Dict[str, str]
) -> Tuple[bool, List[str]]:
    """
    Checks if nation has unlocked all required research techs for the selected components.
    Returns (is_valid, list_of_missing_tech_ids).
    """
    # Get unlocked tech IDs for nation
    stmt = select(NationTech.tech_id).where(NationTech.nation_id == nation_id)
    res = await session.execute(stmt)
    unlocked_techs = set(res.scalars().all())

    missing_techs = []
    for slot, comp_key in component_selections.items():
        if not comp_key:
            continue
        comp = get_component_info(slot, comp_key)
        if comp and "required_tech" in comp:
            req_tech = comp["required_tech"]
            if req_tech and req_tech not in unlocked_techs:
                missing_techs.append(req_tech)

    return (len(missing_techs) == 0, missing_techs)


async def create_unit_design(
    session: AsyncSession,
    nation_id: int,
    name: str,
    category: str,
    component_selections: Dict[str, str],
) -> UnitDesign:
    """
    Validates components and research requirements, calculates stats,
    and persists a new named UnitDesign model to database.
    """
    cat_cfg = get_category_config(category)
    if not cat_cfg:
        raise ValueError(f"Category '{category}' is invalid.")

    # Research validation
    is_valid, missing_techs = await check_nation_researched_components(
        session, nation_id, component_selections
    )
    if not is_valid:
        raise ValueError(f"Nation lacks required tech(s) for components: {', '.join(missing_techs)}")

    # Compute stats
    calculated = calculate_design_stats(category, component_selections)

    now = utc_now()
    design = UnitDesign(
        nation_id=nation_id,
        name=name.strip(),
        category=category,
        components=component_selections,
        stats=calculated["stats"],
        production_cost=calculated["production_cost"],
        upkeep=calculated["upkeep"],
        build_time=calculated["build_time"],
        created_at=now,
        updated_at=now,
    )
    session.add(design)
    await session.commit()
    await session.refresh(design)

    logger.info("Created unit design", design_id=design.id, name=design.name, category=category)
    return design


async def list_nation_designs(session: AsyncSession, nation_id: int) -> List[UnitDesign]:
    """Returns all saved unit designs owned by a given nation."""
    stmt = select(UnitDesign).where(UnitDesign.nation_id == nation_id).order_by(UnitDesign.id.desc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_nation_design(session: AsyncSession, nation_id: int, design_id: int) -> Optional[UnitDesign]:
    """Retrieves a specific unit design if owned by the given nation."""
    stmt = select(UnitDesign).where(UnitDesign.id == design_id, UnitDesign.nation_id == nation_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def delete_nation_design(session: AsyncSession, nation_id: int, design_id: int) -> bool:
    """Deletes a saved unit design owned by a nation."""
    design = await get_nation_design(session, nation_id, design_id)
    if not design:
        return False
    await session.delete(design)
    await session.commit()
    logger.info("Deleted unit design", design_id=design_id, nation_id=nation_id)
    return True


async def clone_design_for_nation(
    session: AsyncSession,
    source_design_id: int,
    target_nation_id: int,
    custom_name: Optional[str] = None,
) -> UnitDesign:
    """Clones an existing unit design (e.g. via blueprint licensing) for a target nation."""
    source = await session.get(UnitDesign, source_design_id)
    if not source:
        raise ValueError(f"Source unit design #{source_design_id} not found.")

    now = utc_now()
    new_name = custom_name.strip() if custom_name else f"{source.name} (Licensed)"
    cloned = UnitDesign(
        nation_id=target_nation_id,
        name=new_name,
        category=source.category,
        components=dict(source.components or {}),
        stats=dict(source.stats or {}),
        production_cost=dict(source.production_cost or {}),
        upkeep=dict(source.upkeep or {}),
        build_time=source.build_time,
        created_at=now,
        updated_at=now,
    )
    session.add(cloned)
    await session.commit()
    await session.refresh(cloned)

    logger.info("Cloned unit design blueprint", source_id=source_design_id, new_id=cloned.id, target_nation=target_nation_id)
    return cloned
