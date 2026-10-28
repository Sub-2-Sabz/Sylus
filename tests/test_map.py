import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sylus.map.renderer import MapRenderer
from scripts.build_world import generate_sample_world


def test_build_world_assets_generation(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_world.ASSETS_DIR", tmp_path)
    monkeypatch.setattr("scripts.build_world.CANVAS_WIDTH", 200)
    monkeypatch.setattr("scripts.build_world.CANVAS_HEIGHT", 100)

    generate_sample_world()

    assert (tmp_path / "province_raster.npz").exists()
    assert (tmp_path / "border_overlay.png").exists()
    assert (tmp_path / "provinces.json").exists()
    assert (tmp_path / "adjacency.json").exists()

    with open(tmp_path / "provinces.json") as f:
        provinces = json.load(f)
        assert len(provinces) > 0

    renderer = MapRenderer(assets_dir=tmp_path)
    assert len(renderer.provinces) == len(provinces)


def test_map_renderer_render_map(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_world.ASSETS_DIR", tmp_path)
    monkeypatch.setattr("scripts.build_world.CANVAS_WIDTH", 200)
    monkeypatch.setattr("scripts.build_world.CANVAS_HEIGHT", 100)
    generate_sample_world()

    renderer = MapRenderer(assets_dir=tmp_path)

    # Political mode
    nation_owners = {1: (255, 0, 0), 2: (0, 255, 0)}
    capitals = [(50, 50)]
    nation_names = {(255, 0, 0): "Red Nation", (0, 255, 0): "Green Nation"}

    img_stream = renderer.render_map(
        nation_owners=nation_owners,
        capitals=capitals,
        mode="political",
        legend_title="Test Map",
        nation_names=nation_names,
    )
    assert img_stream is not None
    img_data = img_stream.getvalue()
    assert len(img_data) > 0

    # Terrain mode
    terrain_stream = renderer.render_map(mode="terrain", legend_title="Test Terrain")
    assert terrain_stream is not None
    assert len(terrain_stream.getvalue()) > 0


@pytest.mark.asyncio
async def test_map_cog_slash_commands(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr("scripts.build_world.ASSETS_DIR", tmp_path)
    monkeypatch.setattr("scripts.build_world.CANVAS_WIDTH", 200)
    monkeypatch.setattr("scripts.build_world.CANVAS_HEIGHT", 100)
    generate_sample_world()

    from sylus.bot.cogs.map import MapCog
    bot = MagicMock()
    cog = MapCog(bot)
    cog.renderer = MapRenderer(assets_dir=tmp_path)

    # Test /map world
    ctx_world = AsyncMock()
    await cog.world_map.callback(cog, ctx_world)
    ctx_world.defer.assert_called_once()
    ctx_world.respond.assert_called_once()

    # Test /map terrain
    ctx_terrain = AsyncMock()
    await cog.terrain_map.callback(cog, ctx_terrain)
    ctx_terrain.defer.assert_called_once()
    ctx_terrain.respond.assert_called_once()

    # Test /map province existing
    ctx_prov = AsyncMock()
    await cog.province_info.callback(cog, ctx_prov, province_id=1)
    ctx_prov.respond.assert_called_once()

    # Test /map province non-existing
    ctx_prov_missing = AsyncMock()
    await cog.province_info.callback(cog, ctx_prov_missing, province_id=9999)
    ctx_prov_missing.respond.assert_called_once()
