import io
import json
import gzip
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import GlobalState, Nation, Province, ResourceLedger, AuditLog, utc_now
from sylus.map.renderer import MapRenderer, ASSETS_DIR
from sylus.engine.economy import process_economy_turn
from sylus.services.research import process_research_turn
from sylus.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TurnResult:
    turn_number: int
    next_turn_at: datetime
    executed: bool
    summary_embed_dict: Dict[str, Any]
    map_bytes: bytes
    snapshot_data: Optional[Dict[str, Any]]
    is_snapshot_due: bool


async def get_or_create_global_state(session: AsyncSession) -> GlobalState:
    """Retrieves or initializes the GlobalState record (id=1)."""
    stmt = select(GlobalState).where(GlobalState.id == 1)
    res = await session.execute(stmt)
    state = res.scalar_one_or_none()

    if state is None:
        duration_sec = int(config.get("turn_engine.turn_duration_seconds", 7200))
        next_turn = utc_now() + timedelta(seconds=duration_sec)
        state = GlobalState(
            id=1,
            turn_number=1,
            next_turn_at=next_turn,
            is_paused=False,
            snapshot_interval_turns=int(config.get("turn_engine.snapshot_interval_turns", 5)),
        )
        session.add(state)
        await session.commit()
        await session.refresh(state)

    return state


async def process_single_turn(session: AsyncSession, force: bool = False) -> Optional[TurnResult]:
    """Atomically processes a single turn if due or forced, using CAS on turn_number."""
    state = await get_or_create_global_state(session)

    if state.is_paused and not force:
        logger.info("Turn processing skipped because global state is paused.", turn_number=state.turn_number)
        return None

    current_turn = state.turn_number
    state_id = state.id
    snapshot_interval = state.snapshot_interval_turns or int(config.get("turn_engine.snapshot_interval_turns", 5))

    duration_sec = int(config.get("turn_engine.turn_duration_seconds", 7200))

    now = utc_now()
    base_time = state.next_turn_at
    if base_time is not None and base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=timezone.utc)
    base_time = base_time or now

    if base_time < now - timedelta(seconds=duration_sec * 50):
        base_time = now

    new_next_turn = base_time + timedelta(seconds=duration_sec)
    if force and new_next_turn <= now:
        new_next_turn = now + timedelta(seconds=duration_sec)

    # Compare-and-Set query to guarantee single execution per turn
    cas_stmt = (
        update(GlobalState)
        .where(GlobalState.id == state_id, GlobalState.turn_number == current_turn)
        .values(
            turn_number=current_turn + 1,
            next_turn_at=new_next_turn,
            updated_at=now,
        )
    )

    cas_result = await session.execute(cas_stmt)
    if cas_result.rowcount == 0:
        logger.warning("CAS turn update matched 0 rows; turn was executed concurrently.", turn_number=current_turn)
        return None

    state.turn_number = current_turn + 1
    state.next_turn_at = new_next_turn
    state.updated_at = now

    # Process turn economy
    await process_economy_turn(session)

    # Process research progression & licenses
    await process_research_turn(session)

    # Record turn audit log entry
    audit = AuditLog(
        action_type="turn_processed",
        entity_type="global_state",
        entity_id=state_id,
        details={"processed_turn": current_turn, "new_turn": current_turn + 1},
        created_at=now,
    )
    session.add(audit)

    # Render world map for summary
    map_bytes = await _render_turn_map(session)

    # Build summary embed payload
    summary_dict = {
        "title": f"Sylus World - Turn {current_turn} Summary",
        "description": f"Turn **{current_turn}** has been processed successfully.",
        "color": 0x3498DB,
        "fields": [
            {"name": "Completed Turn", "value": str(current_turn), "inline": True},
            {"name": "Next Turn At", "value": new_next_turn.strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True},
        ],
        "timestamp": now.isoformat(),
    }

    # Snapshot export if snapshot interval reached
    is_snapshot_due = (current_turn % snapshot_interval == 0) or force
    snapshot_data = await export_snapshot(session) if is_snapshot_due else None

    logger.info("Turn processed successfully", turn_number=current_turn, next_turn_at=new_next_turn.isoformat())

    return TurnResult(
        turn_number=current_turn,
        next_turn_at=new_next_turn,
        executed=True,
        summary_embed_dict=summary_dict,
        map_bytes=map_bytes,
        snapshot_data=snapshot_data,
        is_snapshot_due=is_snapshot_due,
    )


async def _render_turn_map(session: AsyncSession) -> bytes:
    """Renders map image as PNG bytes."""
    try:
        renderer = MapRenderer(assets_dir=ASSETS_DIR)
        # Fetch nation owners mapping if any
        res = await session.execute(select(Province).where(Province.nation_id.isnot(None)))
        provinces = res.scalars().all()
        nation_owners: Dict[int, Any] = {}
        if provinces:
            nation_res = await session.execute(select(Nation))
            nations = {n.id: n for n in nation_res.scalars().all()}
            for p in provinces:
                if p.nation_id in nations:
                    # Convert hex color to RGB tuple
                    hex_col = nations[p.nation_id].color or "#00FF00"
                    hex_col = hex_col.lstrip("#")
                    if len(hex_col) == 6:
                        rgb = (int(hex_col[0:2], 16), int(hex_col[2:4], 16), int(hex_col[4:6], 16))
                        nation_owners[p.id] = rgb

        stream = renderer.render_map(nation_owners=nation_owners)
        return stream.getvalue()
    except Exception as e:
        logger.warning("Failed to render turn map, returning empty image placeholder", error=str(e))
        return b""


async def export_snapshot(session: AsyncSession) -> Dict[str, Any]:
    """Exports full database state to a JSON-serializable dictionary."""
    states = (await session.execute(select(GlobalState))).scalars().all()
    nations = (await session.execute(select(Nation))).scalars().all()
    provinces = (await session.execute(select(Province))).scalars().all()
    resources = (await session.execute(select(ResourceLedger))).scalars().all()
    audits = (await session.execute(select(AuditLog))).scalars().all()

    return {
        "version": 1,
        "exported_at": utc_now().isoformat(),
        "global_state": [
            {
                "id": g.id,
                "turn_number": g.turn_number,
                "next_turn_at": g.next_turn_at.isoformat() if g.next_turn_at else None,
                "is_paused": g.is_paused,
                "map_channel_id": g.map_channel_id,
                "backup_channel_id": g.backup_channel_id,
                "snapshot_interval_turns": g.snapshot_interval_turns,
            }
            for g in states
        ],
        "nations": [
            {
                "id": n.id,
                "name": n.name,
                "discord_user_id": n.discord_user_id,
                "color": n.color,
            }
            for n in nations
        ],
        "provinces": [
            {
                "id": p.id,
                "name": p.name,
                "nation_id": p.nation_id,
                "terrain": p.terrain,
                "is_capital": p.is_capital,
            }
            for p in provinces
        ],
        "resource_ledgers": [
            {
                "id": r.id,
                "nation_id": r.nation_id,
                "resource_type": r.resource_type,
                "balance": r.balance,
            }
            for r in resources
        ],
        "audit_logs": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "actor_id": a.actor_id,
                "details": a.details,
            }
            for a in audits
        ],
    }


async def restore_snapshot(session: AsyncSession, snapshot_data: Dict[str, Any]) -> None:
    """Restores database state from snapshot data dictionary."""
    if snapshot_data.get("version") != 1:
        raise ValueError("Unsupported snapshot version")

    # Clear existing state in reverse dependency order
    await session.execute(delete(ResourceLedger))
    await session.execute(delete(Province))
    await session.execute(delete(Nation))
    await session.execute(delete(AuditLog))
    await session.execute(delete(GlobalState))

    now = utc_now()

    for g in snapshot_data.get("global_state", []):
        next_dt = datetime.fromisoformat(g["next_turn_at"]) if g.get("next_turn_at") else None
        session.add(
            GlobalState(
                id=g["id"],
                turn_number=g["turn_number"],
                next_turn_at=next_dt,
                is_paused=g.get("is_paused", False),
                map_channel_id=g.get("map_channel_id"),
                backup_channel_id=g.get("backup_channel_id"),
                snapshot_interval_turns=g.get("snapshot_interval_turns", 5),
                created_at=now,
                updated_at=now,
            )
        )

    for n in snapshot_data.get("nations", []):
        session.add(
            Nation(
                id=n["id"],
                name=n["name"],
                discord_user_id=n["discord_user_id"],
                color=n.get("color", "#00FF00"),
                created_at=now,
                updated_at=now,
            )
        )

    for p in snapshot_data.get("provinces", []):
        session.add(
            Province(
                id=p["id"],
                name=p["name"],
                nation_id=p.get("nation_id"),
                terrain=p.get("terrain", "plains"),
                is_capital=p.get("is_capital", False),
                created_at=now,
                updated_at=now,
            )
        )

    for r in snapshot_data.get("resource_ledgers", []):
        session.add(
            ResourceLedger(
                id=r["id"],
                nation_id=r["nation_id"],
                resource_type=r["resource_type"],
                balance=r["balance"],
                created_at=now,
                updated_at=now,
            )
        )

    for a in snapshot_data.get("audit_logs", []):
        session.add(
            AuditLog(
                id=a["id"],
                action_type=a["action_type"],
                entity_type=a["entity_type"],
                entity_id=a.get("entity_id"),
                actor_id=a.get("actor_id"),
                details=a.get("details"),
                created_at=now,
            )
        )

    await session.commit()
    logger.info("Restored database state from snapshot successfully.")
