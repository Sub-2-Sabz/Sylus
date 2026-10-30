import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select, func

from sylus.db.models import Province, Nation
from sylus.services.seed_world import sync_provinces_db
from sylus.services.province_search import get_province_index, province_autocomplete
from sylus.map.renderer import MapRenderer


def test_world_provinces_non_empty_and_valid():
    prov_file = Path("sylus/assets/world/provinces.json")
    assert prov_file.exists(), "provinces.json asset missing"

    with open(prov_file, "r", encoding="utf-8") as f:
        provinces = json.load(f)

    assert len(provinces) >= 4000, f"Expected >4000 provinces, found {len(provinces)}"

    for pid, p in provinces.items():
        assert p.get("name"), f"Province {pid} missing name"
        assert p.get("country"), f"Province {pid} missing country"
        assert p.get("code"), f"Province {pid} missing code"
        assert p.get("display_name"), f"Province {pid} missing display_name"
        assert p.get("search_name"), f"Province {pid} missing search_name"


def test_display_names_unique():
    prov_file = Path("sylus/assets/world/provinces.json")
    with open(prov_file, "r", encoding="utf-8") as f:
        provinces = json.load(f)

    display_names = [p["display_name"] for p in provinces.values()]
    unique_names = set(display_names)
    duplicates = [name for name in display_names if display_names.count(name) > 1]

    assert len(display_names) == len(unique_names), f"Duplicate display names found: {set(duplicates)}"


def test_autocomplete_sensible_results():
    index = get_province_index()

    # Query "geo"
    res_geo = index.search("geo", limit=25)
    names_geo = [p["display_name"] for p in res_geo]
    assert any("Georgia" in n for n in names_geo), f"Expected 'Georgia' in results for 'geo': {names_geo}"

    # Query "new yo"
    res_ny = index.search("new yo", limit=10)
    names_ny = [p["display_name"] for p in res_ny]
    assert any("New York" in n for n in names_ny), f"Expected 'New York' in results for 'new yo': {names_ny}"

    # Query "são paulo"
    res_sp = index.search("são paulo", limit=10)
    names_sp = [p["display_name"] for p in res_sp]
    assert any("São Paulo" in n for n in names_sp), f"Expected 'São Paulo' in results for 'são paulo': {names_sp}"

    # Query "bavaria"
    res_bav = index.search("bavaria", limit=10)
    names_bav = [p["display_name"] for p in res_bav] + [a for p in res_bav for a in p.get("raw", {}).get("aliases", [])]
    assert any("Bavaria" in n or "Bayern" in n for n in names_bav), f"Expected 'Bavaria/Bayern' in results for 'bavaria': {names_bav}"


@pytest.mark.asyncio
async def test_seed_step_idempotent(db_session):
    # First sync was performed in conftest fixture
    count1 = (await db_session.execute(select(func.count(Province.id)))).scalar()

    # Perform second sync
    synced = await sync_provinces_db(db_session)
    count2 = (await db_session.execute(select(func.count(Province.id)))).scalar()

    assert count1 == count2
    assert synced == count1


@pytest.mark.asyncio
async def test_province_cogs_and_no_raw_ids(db_session):
    from sylus.bot.cogs.province import ProvinceCog
    bot = MagicMock()
    bot.renderer = MapRenderer()
    cog = ProvinceCog(bot)

    # Test /province info
    ctx_info = AsyncMock()
    ctx_info.author.id = 12345
    await cog.province_info.callback(cog, ctx_info, province="New York")
    ctx_info.respond.assert_called_once()
    kwargs = ctx_info.respond.call_args.kwargs
    embed = kwargs.get("embed")
    assert embed is not None
    assert "New York" in embed.title

    # Test /province search
    ctx_search = AsyncMock()
    ctx_search.author.id = 12345
    await cog.province_search.callback(cog, ctx_search, query="São Paulo")
    ctx_search.respond.assert_called_once()

    # Test /province list
    ctx_list = AsyncMock()
    ctx_list.author.id = 12345
    await cog.province_list.callback(cog, ctx_list, country="Germany")
    ctx_list.respond.assert_called_once()
