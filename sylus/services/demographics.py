import random
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, Province, ResourceLedger, AuditLog
from sylus.logging import get_logger

logger = get_logger(__name__)


def clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, val))


async def update_demographics_turn(session: AsyncSession) -> Dict[str, Any]:
    """Updates demographic statistics, health, education, crime, pollution, corruption, and unrest for all nations."""
    res = await session.execute(select(Nation))
    nations = res.scalars().all()

    rates = config.get("demographics.rates", {})
    base_health_recovery = float(rates.get("base_health_recovery", 0.02))
    health_pollution_impact = float(rates.get("health_pollution_impact", 0.10))
    education_growth = float(rates.get("education_growth", 0.01))
    crime_unemployment_impact = float(rates.get("crime_unemployment_impact", 0.20))
    crime_happiness_impact = float(rates.get("crime_happiness_impact", 0.15))
    corruption_tax_impact = float(rates.get("corruption_tax_impact", 0.10))
    corruption_edu_mitigation = float(rates.get("corruption_education_mitigation", 0.05))
    pollution_decay_rate = float(rates.get("pollution_decay_rate", 0.01))

    unrest_summary = {"protests": 0, "riots": 0, "civil_wars": 0, "secessions": 0}

    for nation in nations:
        # Demographics work/pop breakdown
        worker_r = float(config.get("demographics.defaults.worker_ratio", 0.70))
        soldier_r = float(config.get("demographics.defaults.soldier_ratio", 0.05))
        nation.workers = int(nation.population * worker_r)
        nation.soldiers = int(nation.population * soldier_r)
        nation.unemployed = max(0, nation.population - nation.workers - nation.soldiers)

        unemployment_rate = (nation.unemployed / max(1, nation.population))

        # Health update
        health_delta = base_health_recovery - (nation.pollution * health_pollution_impact)
        nation.health = clamp(nation.health + health_delta)

        # Education update
        nation.education = clamp(nation.education + education_growth)

        # Pollution decay
        nation.pollution = clamp(nation.pollution - pollution_decay_rate)

        # Crime update
        target_crime = (unemployment_rate * crime_unemployment_impact) + ((1.0 - nation.happiness) * crime_happiness_impact)
        nation.crime = clamp((nation.crime * 0.7) + (target_crime * 0.3))

        # Corruption update
        target_corruption = (nation.tax_rate * corruption_tax_impact) - (nation.education * corruption_edu_mitigation)
        nation.corruption = clamp((nation.corruption * 0.8) + (max(0.0, target_corruption) * 0.2))

        # Happiness update based on tax, health, education, crime, pollution, corruption
        tax_optimal = float(config.get("balance.tax_rate_optimal", 0.25))
        tax_penalty = max(0.0, nation.tax_rate - tax_optimal) * 1.5
        calc_happiness = 0.5 + (0.2 * nation.health) + (0.2 * nation.education) - (0.2 * nation.crime) - (0.1 * nation.pollution) - (0.1 * nation.corruption) - tax_penalty
        nation.happiness = clamp(calc_happiness)

        # Evaluate unrest ladder
        unrest_res = await evaluate_unrest_ladder(session, nation)
        if unrest_res["unrest_level"] == "protests":
            unrest_summary["protests"] += 1
        elif unrest_res["unrest_level"] == "riots":
            unrest_summary["riots"] += 1
        elif unrest_res["unrest_level"] == "civil_war":
            unrest_summary["civil_wars"] += 1
        if unrest_res.get("seceded"):
            unrest_summary["secessions"] += 1

    return unrest_summary


async def evaluate_unrest_ladder(session: AsyncSession, nation: Nation) -> Dict[str, Any]:
    """Evaluates nation happiness against unrest thresholds and handles civil war secession."""
    thresholds = config.get("demographics.unrest_ladder.thresholds", {})
    p_thresh = float(thresholds.get("protests", 0.60))
    r_thresh = float(thresholds.get("riots", 0.40))
    c_thresh = float(thresholds.get("civil_war", 0.20))

    prev_unrest = nation.unrest_level
    seceded_prov_id = None

    if nation.happiness < c_thresh:
        nation.unrest_level = "civil_war"
        # Check civil war secession
        sec_chance = float(config.get("demographics.unrest_ladder.civil_war_secession_chance", 0.50))
        if random.random() < sec_chance:
            # Find non-capital province to secede
            prov_res = await session.execute(
                select(Province).where(Province.nation_id == nation.id, Province.is_capital == False)
            )
            candidates = prov_res.scalars().all()
            if candidates:
                seceded_prov = random.choice(candidates)
                seceded_prov.nation_id = None
                seceded_prov_id = seceded_prov.id
                logger.info("Province seceded due to civil war", nation_id=nation.id, province_id=seceded_prov.id)
    elif nation.happiness < r_thresh:
        nation.unrest_level = "riots"
    elif nation.happiness < p_thresh:
        nation.unrest_level = "protests"
    else:
        nation.unrest_level = "normal"

    return {
        "nation_id": nation.id,
        "unrest_level": nation.unrest_level,
        "previous_unrest": prev_unrest,
        "seceded": seceded_prov_id is not None,
        "seceded_province_id": seceded_prov_id,
    }


async def apply_unrest_response(session: AsyncSession, nation_id: int, response_type: str) -> Dict[str, Any]:
    """Applies player policy response to unrest with resource costs and stat trade-offs."""
    responses = config.get("demographics.player_responses", {})
    if response_type not in responses:
        raise ValueError(f"Invalid unrest response type: {response_type}")

    spec = responses[response_type]

    # Check nation exists
    n_res = await session.execute(select(Nation).where(Nation.id == nation_id))
    nation = n_res.scalar_one_or_none()
    if not nation:
        raise ValueError("Nation not found")

    # Check money cost
    cost_money = float(spec.get("cost_money", 0.0))
    r_res = await session.execute(
        select(ResourceLedger).where(ResourceLedger.nation_id == nation_id, ResourceLedger.resource_type == "money")
    )
    money_ledger = r_res.scalar_one_or_none()
    if not money_ledger or money_ledger.balance < cost_money:
        raise ValueError(f"Insufficient money. Required: {cost_money}, Available: {money_ledger.balance if money_ledger else 0.0}")

    # Deduct cost
    money_ledger.balance -= cost_money

    # Apply trade-offs
    if "happiness_bonus" in spec:
        nation.happiness = clamp(nation.happiness + float(spec["happiness_bonus"]))
    if "happiness_impact" in spec:
        nation.happiness = clamp(nation.happiness + float(spec["happiness_impact"]))
    if "education_bonus" in spec:
        nation.education = clamp(nation.education + float(spec["education_bonus"]))
    if "health_bonus" in spec:
        nation.health = clamp(nation.health + float(spec["health_bonus"]))
    if "health_impact" in spec:
        nation.health = clamp(nation.health + float(spec["health_impact"]))
    if "crime_reduction" in spec:
        nation.crime = clamp(nation.crime - float(spec["crime_reduction"]))
    if "war_support_bonus" in spec:
        nation.war_support = clamp(nation.war_support + float(spec["war_support_bonus"]))
    if "corruption_increase" in spec:
        nation.corruption = clamp(nation.corruption + float(spec["corruption_increase"]))

    if spec.get("pop_kill_percent"):
        kill_pct = float(spec["pop_kill_percent"])
        nation.population = max(100, int(nation.population * (1.0 - kill_pct)))

    if spec.get("force_reset_unrest"):
        nation.unrest_level = "normal"
    elif "unrest_reduction" in spec:
        ladder = ["normal", "protests", "riots", "civil_war"]
        idx = ladder.index(nation.unrest_level) if nation.unrest_level in ladder else 0
        new_idx = max(0, idx - int(spec["unrest_reduction"]))
        nation.unrest_level = ladder[new_idx]

    audit = AuditLog(
        action_type="unrest_response",
        entity_type="nation",
        entity_id=nation.id,
        actor_id=nation.discord_user_id,
        details={"response_type": response_type, "cost_money": cost_money, "new_unrest_level": nation.unrest_level},
    )
    session.add(audit)
    await session.commit()

    return {
        "success": True,
        "response_type": response_type,
        "cost_money": cost_money,
        "unrest_level": nation.unrest_level,
        "happiness": nation.happiness,
    }
