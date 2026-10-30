import sys
import tracemalloc
import resource
import os
from pathlib import Path

# Add repo root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

tracemalloc.start()


def get_memory_info():
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    curr_b, peak_b = tracemalloc.get_traced_memory()
    return rss_mb, curr_b / (1024 * 1024), peak_b / (1024 * 1024)


def print_memory_step(step_name: str):
    rss, curr, peak = get_memory_info()
    print(f"[{step_name:<25}] RSS: {rss:6.2f} MB | Heap: {curr:6.2f} MB (Peak: {peak:6.2f} MB)")


def main():
    print("=== Sylus Memory Profile ===")
    print_memory_step("0. Initial Baseline")

    import sylus.config
    import sylus.logging
    sylus.logging.setup_logging()
    from sylus.bot.bot import create_bot
    _bot = create_bot()
    print_memory_step("1. App Core Loaded")

    from sylus.map.renderer import MapRenderer, ASSETS_DIR
    renderer = MapRenderer(assets_dir=ASSETS_DIR)
    print_memory_step("2. World Assets Loaded")

    _stream = renderer.render_map(mode="political")
    print_memory_step("3. Rendered One Map")

    print("===========================")


if __name__ == "__main__":
    main()
