import pytest
from sylus.config import Config

def test_config_loading(tmp_path):
    yaml_content = """
balance:
  tax_rate_default: 0.15
  starting_gold: 500
"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "balance.yaml"
    config_file.write_text(yaml_content)

    cfg = Config(config_dir=config_dir)
    assert cfg.get("balance.tax_rate_default") == 0.15
    assert cfg.get("balance.starting_gold") == 500
    assert cfg.get("balance.non_existent", "default_val") == "default_val"

def test_default_config_properties(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "test_token_123")
    monkeypatch.setenv("HTTP_PORT", "9090")

    cfg = Config()
    assert cfg.discord_token == "test_token_123"
    assert cfg.http_port == 9090
