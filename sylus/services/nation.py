from typing import Optional, Dict, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, Province, ResourceLedger, Building, AuditLog, utc_now
from sylus.logging import get_logger

logger = get_logger(__name__)

async def create_nation(
    session: AsyncSession,
    discord_user_id: int,
    name: str,
    leader_name: str,
    capital_province_id: int,
    color: str = "#00FF00",
    flag_url: Optional[str] = None,
    government_type: str = "republic",
    ideology: str = "centrism",
    starting_policy: Optional[str] = None,
) -> Nation:
    """Creates a new nation ensuring one nation per user and unowned capital province."""
    # Check if user already owns a nation
    existing_user_nation = (
        await session.execute(select(Nation).where(Nation.discord_user_id == discord_user_id))
    ).scalar_one_or_none()
    if existing_user_nation:
        raise ValueError("You already own a nation! Each user can only created/own one nation.")

    # Check if name is taken
    existing_name = (
        await session.execute(select(Nation).where(Nation.name == name))
    ).scalar_one_or_none()
    if existing_name:
        raise ValueError(f"The nation name '{name}' is already taken.")

    # Check capital province
    prov = (
        await session.execute(select(Province).where(Province.id == capital_province_id))
    ).scalar_one_or_none()
    if not prov:
        raise ValueError(f"Province with ID {capital_province_id} does not exist.")
    if prov.nation_id is not None:
        raise ValueError(f"Province '{prov.name}' is already owned by another nation.")

    # Initialize active policies
    active_policies = {}
    policies_cfg = config.get("policies", {})
    if starting_policy and starting_policy in policies_cfg:
        active_policies[starting_policy] = True

    # Validate government type
    govs_cfg = config.get("governments", {})
    if government_type not in govs_cfg:
        government_type = "republic"

    start_pop = int(config.get("balance.starting_population", 10000))
    start_happy = float(config.get("balance.starting_happiness", 0.80))
    start_tax = float(config.get("balance.tax_rate_default", 0.15))

    nation = Nation(
        name=name,
        discord_user_id=discord_user_id,
        color=color,
        leader_name=leader_name,
        flag_url=flag_url,
        government_type=government_type,
        ideology=ideology,
        tax_rate=start_tax,
        happiness=start_happy,
        population=start_pop,
        score=100.0,
        active_policies=active_policies,
        policy_cooldowns={},
    )
    session.add(nation)
    await session.flush()

    # Assign capital province
    prov.nation_id = nation.id
    prov.is_capital = True
    prov.population = start_pop

    # Initialize starting resources
    starting_res = config.get("balance.starting_resources", {})
    res_types_cfg = config.get("resources.types", [])
    valid_res_names = {r["name"] for r in res_types_cfg}

    for res_name in valid_res_names:
        start_bal = float(starting_res.get(res_name, 0.0))
        session.add(
            ResourceLedger(
                nation_id=nation.id,
                resource_type=res_name,
                balance=start_bal,
            )
        )

    # Log audit
    session.add(
        AuditLog(
            action_type="create_nation",
            entity_type="nation",
            entity_id=nation.id,
            actor_id=discord_user_id,
            details={"name": name, "capital_province_id": capital_province_id},
            created_at=utc_now(),
        )
    )

    await session.commit()
    await session.refresh(nation)
    return nation


async def set_policy(session: AsyncSession, nation: Nation, policy_key: str, enable: bool) -> str:
    policies_cfg = config.get("policies", {})
    if policy_key not in policies_cfg:
        raise ValueError(f"Unknown policy '{policy_key}'.")

    p_info = policies_cfg[policy_key]
    cd_turns = int(p_info.get("cooldown_turns", 12))

    current_cds = dict(nation.policy_cooldowns or {})
    if current_cds.get(policy_key, 0) > 0:
        raise ValueError(
            f"Policy '{policy_key}' is on cooldown for {current_cds[policy_key]} more turns."
        )

    active = dict(nation.active_policies or {})
    if enable:
        # Check transition cost
        cost = p_info.get("transition_cost", {})
        money_cost = float(cost.get("money", 0.0))
        if money_cost > 0:
            m_res = (
                await session.execute(
                    select(ResourceLedger).where(
                        ResourceLedger.nation_id == nation.id,
                        ResourceLedger.resource_type == "money",
                    )
                )
            ).scalar_one_or_none()
            if not m_res or m_res.balance < money_cost:
                raise ValueError(f"Insufficient funds to adopt policy ({money_cost} money required).")
            m_res.balance -= money_cost

        active[policy_key] = True
        msg = f"Policy '{p_info['name']}' has been activated."
    else:
        active.pop(policy_key, None)
        msg = f"Policy '{p_info['name']}' has been deactivated."

    current_cds[policy_key] = cd_turns
    nation.active_policies = active
    nation.policy_cooldowns = current_cds

    await session.commit()
    return msg


async def build_structure(session: AsyncSession, nation: Nation, province_id: int, building_type: str) -> Building:
    prov = (
        await session.execute(
            select(Province).where(Province.id == province_id, Province.nation_id == nation.id)
        )
    ).scalar_one_or_none()
    if not prov:
        raise ValueError("Province not found or not owned by your nation.")

    b_cfg = config.get("buildings", {}).get(building_type)
    if not b_cfg:
        raise ValueError(f"Unknown building type '{building_type}'.")

    # Check slot cap
    existing_buildings = (
        await session.execute(select(Building).where(Building.province_id == province_id))
    ).scalars().all()
    used_slots = sum(config.get("buildings", {}).get(b.building_type, {}).get("slot_cost", 1) for b in existing_buildings)
    req_slots = int(b_cfg.get("slot_cost", 1))

    if used_slots + req_slots > prov.slot_cap:
        raise ValueError(f"Not enough building slots in {prov.name} ({used_slots}/{prov.slot_cap} used).")

    # Check resource costs
    costs = b_cfg.get("cost", {})
    res_ledgers = (
        await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation.id))
    ).scalars().all()
    ledger_map = {r.resource_type: r for r in res_ledgers}

    for res_type, amount in costs.items():
        ledger = ledger_map.get(res_type)
        if not ledger or ledger.balance < float(amount):
            raise ValueError(f"Insufficient {res_type} (requires {amount}).")

    # Deduct cost
    for res_type, amount in costs.items():
        ledger_map[res_type].balance -= float(amount)

    turns_req = int(b_cfg.get("construction_turns", 1))
    building = Building(
        province_id=province_id,
        nation_id=nation.id,
        building_type=building_type,
        level=1,
        turns_remaining=turns_req,
    )
    session.add(building)
    await session.commit()
    await session.refresh(building)
    return building


async def upgrade_structure(session: AsyncSession, nation: Nation, building_id: int) -> Building:
    bldg = (
        await session.execute(
            select(Building).where(Building.id == building_id, Building.nation_id == nation.id)
        )
    ).scalar_one_or_none()
    if not bldg:
        raise ValueError("Building not found or not owned by your nation.")

    if bldg.turns_remaining > 0:
        raise ValueError("Cannot upgrade a building currently under construction.")

    b_cfg = config.get("buildings", {}).get(bldg.building_type, {})
    costs = b_cfg.get("cost", {})
    upgrade_mult = bldg.level + 1

    res_ledgers = (
        await session.execute(select(ResourceLedger).where(ResourceLedger.nation_id == nation.id))
    ).scalars().all()
    ledger_map = {r.resource_type: r for r in res_ledgers}

    for res_type, amount in costs.items():
        req = float(amount) * upgrade_mult
        ledger = ledger_map.get(res_type)
        if not ledger or ledger.balance < req:
            raise ValueError(f"Insufficient {res_type} for upgrade (requires {req}).")

    for res_type, amount in costs.items():
        req = float(amount) * upgrade_mult
        ledger_map[res_type].balance -= req

    bldg.level += 1
    bldg.turns_remaining = int(b_cfg.get("construction_turns", 1))
    await session.commit()
    await session.refresh(bldg)
    return bldg


async def demolish_structure(session: AsyncSession, nation: Nation, building_id: int) -> str:
    bldg = (
        await session.execute(
            select(Building).where(Building.id == building_id, Building.nation_id == nation.id)
        )
    ).scalar_one_or_none()
    if not bldg:
        raise ValueError("Building not found or not owned by your nation.")

    b_type = bldg.building_type
    p_id = bldg.province_id
    await session.delete(bldg)
    await session.commit()
    return f"Demolished {b_type.title()} in Province #{p_id}."
