import random
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, NationEvent, ResourceLedger, AuditLog
from sylus.logging import get_logger

logger = get_logger(__name__)


def clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, val))


async def process_narrative_events_turn(session: AsyncSession, turn_number: int) -> List[Dict[str, Any]]:
    """Triggers random narrative events for nations during turn processing using seeded RNG."""
    rng = random.Random(f"event_{turn_number}")

    res = await session.execute(select(Nation))
    nations = res.scalars().all()

    templates = config.get("events.templates", {})
    trigger_chance = float(config.get("events.trigger_chance_per_turn", 0.20))

    triggered_events: List[Dict[str, Any]] = []

    if not templates:
        return triggered_events

    template_keys = list(templates.keys())

    for nation in nations:
        if rng.random() < trigger_chance:
            event_key = rng.choice(template_keys)
            tmpl = templates[event_key]

            e = NationEvent(
                nation_id=nation.id,
                event_id=tmpl["id"],
                title=tmpl["title"],
                description=tmpl["description"],
                choices=tmpl["choices"],
                status="pending",
                created_at_turn=turn_number,
            )
            session.add(e)
            triggered_events.append({"nation_id": nation.id, "event_id": tmpl["id"], "title": tmpl["title"]})

    return triggered_events


async def resolve_event_choice(
    session: AsyncSession,
    nation_id: int,
    event_db_id: int,
    choice_index: int,
) -> Dict[str, Any]:
    """Resolves a pending narrative event for a nation and applies choice effects."""
    res = await session.execute(
        select(NationEvent).where(NationEvent.id == event_db_id, NationEvent.nation_id == nation_id)
    )
    event = res.scalar_one_or_none()
    if not event:
        raise ValueError("Event not found or does not belong to nation")

    if event.status != "pending":
        raise ValueError("Event is already resolved")

    choices = event.choices
    if not isinstance(choices, list) or choice_index < 0 or choice_index >= len(choices):
        raise ValueError(f"Invalid choice index: {choice_index}")

    selected = choices[choice_index]
    effects = selected.get("effects", {})

    # Fetch nation
    n_res = await session.execute(select(Nation).where(Nation.id == nation_id))
    nation = n_res.scalar_one_or_none()
    if not nation:
        raise ValueError("Nation not found")

    # Apply money effect
    if "money" in effects:
        money_change = float(effects["money"])
        m_res = await session.execute(
            select(ResourceLedger).where(ResourceLedger.nation_id == nation_id, ResourceLedger.resource_type == "money")
        )
        ledger = m_res.scalar_one_or_none()
        if ledger:
            ledger.balance = max(0.0, ledger.balance + money_change)

    # Apply research_points effect
    if "research_points" in effects:
        rp_change = float(effects["research_points"])
        rp_res = await session.execute(
            select(ResourceLedger).where(ResourceLedger.nation_id == nation_id, ResourceLedger.resource_type == "research_points")
        )
        rp_ledger = rp_res.scalar_one_or_none()
        if rp_ledger:
            rp_ledger.balance = max(0.0, rp_ledger.balance + rp_change)

    # Apply stat effects
    if "happiness" in effects:
        nation.happiness = clamp(nation.happiness + float(effects["happiness"]))
    if "health" in effects:
        nation.health = clamp(nation.health + float(effects["health"]))
    if "education" in effects:
        nation.education = clamp(nation.education + float(effects["education"]))
    if "pollution" in effects:
        nation.pollution = clamp(nation.pollution + float(effects["pollution"]))
    if "corruption" in effects:
        nation.corruption = clamp(nation.corruption + float(effects["corruption"]))
    if "war_support" in effects:
        nation.war_support = clamp(nation.war_support + float(effects["war_support"]))

    if "unrest" in effects:
        ladder = ["normal", "protests", "riots", "civil_war"]
        idx = ladder.index(nation.unrest_level) if nation.unrest_level in ladder else 0
        new_idx = max(0, min(len(ladder) - 1, idx + int(effects["unrest"])))
        nation.unrest_level = ladder[new_idx]

    event.status = "resolved"
    event.chosen_option = choice_index

    audit = AuditLog(
        action_type="event_resolved",
        entity_type="nation_event",
        entity_id=event.id,
        actor_id=nation.discord_user_id,
        details={"event_id": event.event_id, "chosen_index": choice_index, "label": selected.get("label")},
    )
    session.add(audit)
    await session.commit()

    return {
        "success": True,
        "event_id": event.event_id,
        "chosen_label": selected.get("label"),
        "effects_applied": effects,
    }
