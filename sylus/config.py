import os
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self, config_dir: str | Path | None = None):
        if config_dir is None:
            config_dir = os.getenv("CONFIG_DIR", "config")
        self.config_dir = Path(config_dir)
        self._data: Dict[str, Any] = {}
        self.load_configs()

    def load_configs(self) -> None:
        self._data.clear()
        if not self.config_dir.exists():
            return

        for filepath in self.config_dir.glob("*.yaml"):
            key = filepath.stem
            with open(filepath, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                if isinstance(content, dict) and key in content and len(content) == 1:
                    self._data[key] = content[key]
                else:
                    self._data[key] = content

        for filepath in self.config_dir.glob("*.yml"):
            key = filepath.stem
            if key in self._data:
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                if isinstance(content, dict) and key in content and len(content) == 1:
                    self._data[key] = content[key]
                else:
                    self._data[key] = content

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        val: Any = self._data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    @property
    def discord_token(self) -> str:
        return os.getenv("DISCORD_TOKEN", "")

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///sylus.db")

    @property
    def http_host(self) -> str:
        return os.getenv("HTTP_HOST", "0.0.0.0")

    @property
    def http_port(self) -> int:
        return int(os.getenv("HTTP_PORT", "8080"))

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")

config = Config()
