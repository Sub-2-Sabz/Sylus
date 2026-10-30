import json
from pathlib import Path
from typing import Dict, Any, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.models import Province
from sylus.logging import get_logger

logger = get_logger(__name__)

ASSETS_DIR = Path(config.get("map.assets_dir", "sylus/assets/world"))

async def sync_provinces_db(session: AsyncSession, assets_dir: Optional[Path] = None) -> int:
    """Idempotently syncs provinces from provinces.json into the database."""
    target_dir = Path(assets_dir) if assets_dir else ASSETS_DIR
    prov_file = target_dir / "provinces.json"

    if not prov_file.exists():
        logger.warning("provinces.json not found, skipping province DB sync", path=str(prov_file))
        return 0

    with open(prov_file, "r", encoding="utf-8") as f:
        json_data: Dict[str, Dict[str, Any]] = json.load(f)

    stmt = select(Province)
    result = await session.execute(stmt)
    existing_provinces = result.scalars().all()

    by_code = {p.code: p for p in existing_provinces if p.code}
    by_id = {p.id: p for p in existing_provinces}

    count = 0
    for key, pdata in json_data.items():
        p_id = int(pdata["id"])
        code = pdata["code"]

        prov = by_code.get(code) or by_id.get(p_id)

        if prov is not None:
            # Update existing province attributes, preserving owners & capitals
            prov.code = code
            prov.name = pdata["name"]
            prov.country = pdata.get("country", "Unknown")
            prov.country_code = pdata.get("country_code", "XX")
            prov.display_name = pdata.get("display_name", pdata["name"])
            prov.search_name = pdata.get("search_name", pdata["name"].lower())
            prov.aliases = pdata.get("aliases", [])
            prov.terrain = pdata.get("terrain", "plains")
            prov.climate = pdata.get("climate", "temperate")
            prov.deposits = pdata.get("deposits", {})
            prov.population_capacity = pdata.get("population_capacity", 100000)
            prov.centroid_coords = pdata.get("capital_coords", [0, 0])
        else:
            # Create new province
            new_prov = Province(
                id=p_id,
                code=code,
                name=pdata["name"],
                country=pdata.get("country", "Unknown"),
                country_code=pdata.get("country_code", "XX"),
                display_name=pdata.get("display_name", pdata["name"]),
                search_name=pdata.get("search_name", pdata["name"].lower()),
                aliases=pdata.get("aliases", []),
                terrain=pdata.get("terrain", "plains"),
                climate=pdata.get("climate", "temperate"),
                deposits=pdata.get("deposits", {}),
                population_capacity=pdata.get("population_capacity", 100000),
                centroid_coords=pdata.get("capital_coords", [0, 0]),
                is_capital=False,
                nation_id=None,
                population=10000,
                infrastructure=1,
                slot_cap=5,
            )
            session.add(new_prov)
        count += 1

    try:
        bind = session.get_bind()
        if bind and "sqlite" in str(bind.url):
            await session.execute(text("INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES ('provinces', (SELECT COALESCE(MAX(id), 0) FROM provinces))"))
    except Exception as e:
        logger.debug("Sequence update skipped", error=str(e))

    await session.commit()
    logger.info("Province DB sync completed", synced_count=count)
    return count
