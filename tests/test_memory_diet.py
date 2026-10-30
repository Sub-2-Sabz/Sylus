import sys
import subprocess
from pathlib import Path
import pytest

from sylus.map.renderer import RenderedMapCache
from sylus.logging import log_memory_usage, get_process_rss_mb


def test_rendered_map_cache_item_cap():
    cache = RenderedMapCache(max_items=3, max_bytes=100000)
    cache.put("key1", b"a" * 100)
    cache.put("key2", b"b" * 100)
    cache.put("key3", b"c" * 100)
    assert cache.size == 3

    # Adding 4th item should evict key1 (LRU)
    cache.put("key4", b"d" * 100)
    assert cache.size == 3
    assert cache.get("key1") is None
    assert cache.get("key2") == b"b" * 100
    assert cache.get("key4") == b"d" * 100


def test_rendered_map_cache_byte_cap():
    cache = RenderedMapCache(max_items=10, max_bytes=500)
    cache.put("key1", b"x" * 200)
    cache.put("key2", b"y" * 200)
    assert cache.total_bytes == 400

    # Adding key3 (200 bytes) will exceed 500 bytes max_bytes, so key1 should be evicted
    cache.put("key3", b"z" * 200)
    assert cache.total_bytes <= 500
    assert cache.get("key1") is None
    assert cache.get("key2") == b"y" * 200
    assert cache.get("key3") == b"z" * 200


def test_app_imports_without_test_packages():
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable,
        "-c",
        "import sys, os; sys.path.insert(0, '.'); import sylus.main; assert 'pytest' not in sys.modules and 'pytest_asyncio' not in sys.modules, 'Test-only package loaded in runtime import!'",
    ]
    res = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    assert res.returncode == 0, f"Import test failed with stderr: {res.stderr}"


def test_memory_logging_func():
    rss = get_process_rss_mb()
    assert rss > 0.0
    logged_rss = log_memory_usage("Unit Test")
    assert logged_rss > 0.0
