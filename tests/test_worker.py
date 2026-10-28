import json
import pytest
from pathlib import Path

def test_worker_js_structure():
    worker_path = Path("workers/keepalive/worker.js")
    assert worker_path.exists()
    content = worker_path.read_text(encoding="utf-8")

    assert "export default" in content
    assert "async scheduled(" in content
    assert "async fetch(" in content
    assert "pingTarget(" in content
    assert "/health" in content

def test_wrangler_jsonc_valid():
    wrangler_path = Path("workers/keepalive/wrangler.jsonc")
    assert wrangler_path.exists()
    content = wrangler_path.read_text(encoding="utf-8")

    data = json.loads(content)
    assert data["name"] == "sylus-keepalive"
    assert data["main"] == "worker.js"
    assert "triggers" in data
    assert "crons" in data["triggers"]
    assert "*/5 * * * *" in data["triggers"]["crons"]
