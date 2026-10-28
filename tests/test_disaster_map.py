import pytest
from sylus.map.renderer import MapRenderer, ASSETS_DIR


def test_map_renderer_with_disaster_zones():
    renderer = MapRenderer(assets_dir=ASSETS_DIR)

    nation_owners = {2: (0, 255, 0), 4: (0, 0, 255)}
    disaster_zones = {2: "epidemic", 4: "earthquake"}

    img_stream = renderer.render_map(
        nation_owners=nation_owners,
        disaster_zones=disaster_zones,
        mode="political",
        legend_title="Disaster Map Test",
    )

    img_bytes = img_stream.getvalue()
    assert len(img_bytes) > 0
    assert img_bytes.startswith(b"\x89PNG")
