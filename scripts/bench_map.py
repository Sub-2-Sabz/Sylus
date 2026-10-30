import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sylus.map.renderer import MapRenderer
from sylus.services.province_search import get_province_index

def bench():
    tracemalloc.start()
    t0 = time.perf_counter()

    print("--- Benchmark Start ---")

    # 1. Load Renderer and Assets
    t_load_start = time.perf_counter()
    renderer = MapRenderer()
    t_load = time.perf_counter() - t_load_start
    print(f"Asset loading time: {t_load * 1000:.2f} ms")

    # 2. Render Full Political Map
    t_pol_start = time.perf_counter()
    owners = {i: (200, 50, 50) for i in range(1, 100)}
    capitals = [(500, 250)]
    stream_pol = renderer.render_map(nation_owners=owners, capitals=capitals, mode="political")
    t_pol = time.perf_counter() - t_pol_start
    print(f"Full political map render time: {t_pol * 1000:.2f} ms (size: {len(stream_pol.getvalue()) / 1024:.1f} KB)")

    # 3. Render Terrain Map
    t_ter_start = time.perf_counter()
    stream_ter = renderer.render_map(mode="terrain")
    t_ter = time.perf_counter() - t_ter_start
    print(f"Terrain map render time: {t_ter * 1000:.2f} ms (size: {len(stream_ter.getvalue()) / 1024:.1f} KB)")

    # 4. Render Region Zoom Map
    t_reg_start = time.perf_counter()
    stream_reg, _ = renderer.render_region_map("New York")
    t_reg = time.perf_counter() - t_reg_start
    print(f"Region map render time: {t_reg * 1000:.2f} ms (size: {len(stream_reg.getvalue()) / 1024:.1f} KB)")

    # 5. Autocomplete Search Performance
    index = get_province_index()
    t_auto_start = time.perf_counter()
    for q in ["geo", "new yo", "são paulo", "bavaria", "tokyo", "paris"]:
        _ = index.search(q, limit=25)
    t_auto = time.perf_counter() - t_auto_start
    print(f"6 Autocomplete queries total time: {t_auto * 1000:.2f} ms ({t_auto / 6 * 1000:.3f} ms / query)")

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Current Memory Usage: {current / (1024 * 1024):.2f} MB")
    print(f"Peak Memory Usage: {peak / (1024 * 1024):.2f} MB")
    print("--- Benchmark End ---")

if __name__ == "__main__":
    bench()
