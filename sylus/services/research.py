from typing import Dict, Any, List, Optional, Set
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Nation, NationTech, ResearchQueue, TechLicense, ResourceLedger, AuditLog
from sylus.logging import get_logger

logger = get_logger(__name__)


def get_all_tech_definitions() -> Dict[str, Dict[str, Any]]:
    """Loads and flattens all technology definitions from config/research.yaml."""
    research_cfg = config.get("research", {})
    trees = research_cfg.get("trees", {})
    all_techs: Dict[str, Dict[str, Any]] = {}

    for tree_id, tree_data in trees.items():
        tree_name = tree_data.get("name", tree_id.title())

        # Check for military-style components with levels
        components = tree_data.get("components", {})
        for comp_id, comp_info in components.items():
            comp_name = comp_info.get("name", comp_id.title())
            levels = comp_info.get("levels", {})
            for lvl_str, lvl_data in levels.items():
                lvl = int(lvl_str)
                tech_key = f"mil_{comp_id}_{lvl}"
                all_techs[tech_key] = {
                    "tech_id": tech_key,
                    "tree": tree_id,
                    "tree_name": tree_name,
                    "category": comp_name,
                    "name": lvl_data.get("name", f"{comp_name} L{lvl}"),
                    "level": lvl,
                    "rp_cost": float(lvl_data.get("rp_cost", 100)),
                    "prereqs": lvl_data.get("prereqs", []),
                    "description": f"Level {lvl} {comp_name} military component.",
                }

        # Check for standard tree technologies
        techs = tree_data.get("techs", {})
        for tech_id, tech_info in techs.items():
            all_techs[tech_id] = {
                "tech_id": tech_id,
                "tree": tree_id,
                "tree_name": tree_name,
                "category": tree_name,
                "name": tech_info.get("name", tech_id.title()),
                "level": 1,
                "rp_cost": float(tech_info.get("rp_cost", 100)),
                "prereqs": tech_info.get("prereqs", []),
                "description": tech_info.get("description", ""),
            }

    return all_techs


def format_progress_bar(allocated: float, target: float) -> str:
    """Renders a visual progress bar string based on balance config settings."""
    cfg = config.get("research.settings", {})
    length = int(cfg.get("progress_bar_length", 10))
    filled_char = str(cfg.get("filled_char", "█"))
    empty_char = str(cfg.get("empty_char", "░"))

    if target <= 0:
        ratio = 1.0
    else:
        ratio = max(0.0, min(1.0, allocated / target))

    filled_len = int(round(ratio * length))
    empty_len = length - filled_len
    bar = (filled_char * filled_len) + (empty_char * empty_len)
    pct = int(round(ratio * 100))
    return f"[{bar}] {pct}%"


async def get_unlocked_techs(session: AsyncSession, nation_id: int) -> Set[str]:
    """Returns set of tech_ids unlocked by nation or granted via active tech licenses."""
    stmt = select(NationTech.tech_id).where(NationTech.nation_id == nation_id)
    res = await session.execute(stmt)
    unlocked = set(res.scalars().all())

    license_stmt = select(TechLicense.tech_id).where(TechLicense.licensee_id == nation_id)
    license_res = await session.execute(license_stmt)
    licensed = set(license_res.scalars().all())

    return unlocked.union(licensed)


async def get_available_techs(
    session: AsyncSession, nation_id: int, tree_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Returns list of tech objects with current status (unlocked, in_queue, available, locked)."""
    all_techs = get_all_tech_definitions()
    unlocked = await get_unlocked_techs(session, nation_id)

    q_stmt = select(ResearchQueue).where(ResearchQueue.nation_id == nation_id)
    q_res = await session.execute(q_stmt)
    queued_techs = {q.tech_id: q for q in q_res.scalars().all()}

    results = []
    for tech_id, tech_info in all_techs.items():
        if tree_filter and tech_info["tree"].lower() != tree_filter.lower():
            continue

        if tech_id in unlocked:
            status = "UNLOCKED"
        elif tech_id in queued_techs:
            status = "IN_QUEUE"
        else:
            prereqs_met = all(p in unlocked for p in tech_info["prereqs"])
            status = "AVAILABLE" if prereqs_met else "LOCKED"

        item = dict(tech_info)
        item["status"] = status
        if tech_id in queued_techs:
            q_item = queued_techs[tech_id]
            item["allocated_rp"] = q_item.allocated_rp
            item["target_rp"] = q_item.target_rp
            item["queue_position"] = q_item.queue_position
            item["progress_bar"] = format_progress_bar(q_item.allocated_rp, q_item.target_rp)

        results.append(item)

    return results


async def queue_technology(session: AsyncSession, nation: Nation, tech_id: str) -> ResearchQueue:
    """Queues a technology for research after validating prerequisites and status."""
    all_techs = get_all_tech_definitions()
    if tech_id not in all_techs:
        raise ValueError(f"Unknown technology: '{tech_id}'")

    tech_info = all_techs[tech_id]
    unlocked = await get_unlocked_techs(session, nation.id)

    if tech_id in unlocked:
        raise ValueError(f"Technology '{tech_info['name']}' is already unlocked.")

    q_stmt = select(ResearchQueue).where(ResearchQueue.nation_id == nation.id)
    q_items = (await session.execute(q_stmt)).scalars().all()
    if any(q.tech_id == tech_id for q in q_items):
        raise ValueError(f"Technology '{tech_info['name']}' is already in the research queue.")

    missing_prereqs = [p for p in tech_info["prereqs"] if p not in unlocked]
    if missing_prereqs:
        req_names = [all_techs[p]["name"] if p in all_techs else p for p in missing_prereqs]
        raise ValueError(f"Missing prerequisites for '{tech_info['name']}': {', '.join(req_names)}")

    pos = len(q_items) + 1
    new_q = ResearchQueue(
        nation_id=nation.id,
        tech_id=tech_id,
        allocated_rp=0.0,
        target_rp=tech_info["rp_cost"],
        queue_position=pos,
    )
    session.add(new_q)
    await session.commit()
    await session.refresh(new_q)

    logger.info("Queued technology", nation_id=nation.id, tech_id=tech_id, position=pos)
    return new_q


async def cancel_research(session: AsyncSession, nation: Nation, queue_id: int) -> float:
    """Cancels a queued technology and refunds allocated RP to the nation's resource ledger."""
    q_stmt = select(ResearchQueue).where(ResearchQueue.id == queue_id, ResearchQueue.nation_id == nation.id)
    item = (await session.execute(q_stmt)).scalar_one_or_none()

    if not item:
        raise ValueError(f"Research queue item #{queue_id} not found.")

    refunded_rp = item.allocated_rp

    if refunded_rp > 0:
        ledger_stmt = select(ResourceLedger).where(
            ResourceLedger.nation_id == nation.id, ResourceLedger.resource_type == "research_points"
        )
        ledger = (await session.execute(ledger_stmt)).scalar_one_or_none()
        if not ledger:
            ledger = ResourceLedger(nation_id=nation.id, resource_type="research_points", balance=0.0)
            session.add(ledger)
        ledger.balance += refunded_rp

    await session.delete(item)

    # Reorder remaining queue items
    rem_stmt = select(ResearchQueue).where(ResearchQueue.nation_id == nation.id).order_by(ResearchQueue.queue_position)
    rem_items = (await session.execute(rem_stmt)).scalars().all()
    for idx, rem in enumerate(rem_items, start=1):
        rem.queue_position = idx

    await session.commit()
    logger.info("Canceled research", nation_id=nation.id, queue_id=queue_id, refunded_rp=refunded_rp)
    return refunded_rp


async def create_tech_license(
    session: AsyncSession, licensor: Nation, licensee: Nation, tech_id: str, royalty_per_turn: float = 0.0
) -> TechLicense:
    """Creates a technology license granting tech access to licensee nation."""
    all_techs = get_all_tech_definitions()
    if tech_id not in all_techs:
        raise ValueError(f"Unknown technology: '{tech_id}'")

    licensor_techs = await get_unlocked_techs(session, licensor.id)
    if tech_id not in licensor_techs:
        raise ValueError(f"Licensor '{licensor.name}' has not unlocked technology '{all_techs[tech_id]['name']}'.")

    license_record = TechLicense(
        licensor_id=licensor.id,
        licensee_id=licensee.id,
        tech_id=tech_id,
        royalty_per_turn=max(0.0, float(royalty_per_turn)),
    )
    session.add(license_record)
    await session.commit()
    await session.refresh(license_record)

    logger.info("Tech license created", licensor_id=licensor.id, licensee_id=licensee.id, tech_id=tech_id)
    return license_record


async def process_research_turn(session: AsyncSession) -> Dict[str, Any]:
    """Processes research turn logic: allocates RP to queue, unlocks completed techs, handles royalties."""
    all_techs = get_all_tech_definitions()
    nations = (await session.execute(select(Nation))).scalars().all()
    completed_techs_count = 0

    for nation in nations:
        # 1. Process active tech licenses and royalty payments
        licenses = (
            await session.execute(select(TechLicense).where(TechLicense.licensee_id == nation.id))
        ).scalars().all()
        for lic in licenses:
            if lic.royalty_per_turn > 0:
                fee = lic.royalty_per_turn
                # Deduct from licensee money ledger
                e_money = (
                    await session.execute(
                        select(ResourceLedger).where(
                            ResourceLedger.nation_id == nation.id, ResourceLedger.resource_type == "money"
                        )
                    )
                ).scalar_one_or_none()
                if e_money and e_money.balance >= fee:
                    e_money.balance -= fee
                    r_money = (
                        await session.execute(
                            select(ResourceLedger).where(
                                ResourceLedger.nation_id == lic.licensor_id, ResourceLedger.resource_type == "money"
                            )
                        )
                    ).scalar_one_or_none()
                    if r_money:
                        r_money.balance += fee

        # 2. Get RP ledger
        rp_ledger = (
            await session.execute(
                select(ResourceLedger).where(
                    ResourceLedger.nation_id == nation.id, ResourceLedger.resource_type == "research_points"
                )
            )
        ).scalar_one_or_none()

        available_rp = rp_ledger.balance if rp_ledger else 0.0
        if available_rp <= 0:
            continue

        # 3. Process research queue in position order
        q_items = (
            await session.execute(
                select(ResearchQueue)
                .where(ResearchQueue.nation_id == nation.id)
                .order_by(ResearchQueue.queue_position)
            )
        ).scalars().all()

        for q_item in q_items:
            if available_rp <= 0:
                break

            needed = q_item.target_rp - q_item.allocated_rp
            alloc = min(available_rp, needed)
            q_item.allocated_rp += alloc
            available_rp -= alloc

            if q_item.allocated_rp >= q_item.target_rp:
                # Tech completed!
                unlocked_tech = NationTech(nation_id=nation.id, tech_id=q_item.tech_id)
                session.add(unlocked_tech)
                await session.delete(q_item)
                completed_techs_count += 1

                tech_name = all_techs.get(q_item.tech_id, {}).get("name", q_item.tech_id)
                audit = AuditLog(
                    action_type="research_completed",
                    entity_type="nation",
                    entity_id=nation.id,
                    details={"tech_id": q_item.tech_id, "tech_name": tech_name},
                )
                session.add(audit)
                logger.info("Technology research completed", nation_id=nation.id, tech_id=q_item.tech_id)

        # Update remaining RP balance in ledger
        if rp_ledger:
            rp_ledger.balance = available_rp

        # Reorder queue if items were completed
        rem_q = (
            await session.execute(
                select(ResearchQueue)
                .where(ResearchQueue.nation_id == nation.id)
                .order_by(ResearchQueue.queue_position)
            )
        ).scalars().all()
        for idx, item in enumerate(rem_q, start=1):
            item.queue_position = idx

    return {"completed_techs": completed_techs_count}
