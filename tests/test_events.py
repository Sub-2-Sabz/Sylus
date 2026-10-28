import pytest
from sqlalchemy import select
from sylus.db.models import Nation, NationEvent, ResourceLedger
from sylus.services.events import process_narrative_events_turn, resolve_event_choice


@pytest.mark.asyncio
async def test_narrative_events_and_resolution(db_session):
    nation = Nation(
        id=1,
        name="Eventia",
        discord_user_id=555666777,
        population=10000,
        happiness=0.70,
        unrest_level="normal",
    )
    db_session.add(nation)

    money = ResourceLedger(nation_id=nation.id, resource_type="money", balance=5000.0)
    db_session.add(money)
    await db_session.commit()

    # Process narrative events turn
    events_triggered = await process_narrative_events_turn(db_session, turn_number=1)

    # Manually create a pending event if rng didn't trigger
    ev_res = await db_session.execute(
        select(NationEvent).where(NationEvent.nation_id == nation.id, NationEvent.status == "pending")
    )
    event = ev_res.scalar_one_or_none()

    if not event:
        event = NationEvent(
            nation_id=nation.id,
            event_id="labor_strike",
            title="Widespread Labor Strike",
            description="Workers demand better conditions.",
            choices=[
                {"label": "Meet worker demands", "effects": {"money": -1000.0, "happiness": 0.10}},
                {"label": "Enforce work", "effects": {"happiness": -0.10}},
            ],
            status="pending",
            created_at_turn=1,
        )
        db_session.add(event)
        await db_session.commit()

    # Resolve event choice index 0
    res = await resolve_event_choice(db_session, nation.id, event.id, choice_index=0)
    assert res["success"] is True
    assert res["chosen_label"] == "Meet worker demands"

    await db_session.refresh(event)
    assert event.status == "resolved"
    assert event.chosen_option == 0
