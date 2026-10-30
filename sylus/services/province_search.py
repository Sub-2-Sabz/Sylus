import json
import unicodedata
from pathlib import Path
from typing import Dict, List, Any, Optional
import discord

from sylus.config import config
from sylus.logging import get_logger

logger = get_logger(__name__)

ASSETS_DIR = Path(config.get("map.assets_dir", "sylus/assets/world"))

def make_search_name(text: str) -> str:
    """Returns lowercase, accent-free search string."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_bytes = nfkd.encode("ASCII", "ignore")
    return ascii_bytes.decode("utf-8").lower().strip()

class ProvinceIndex:
    _instance: Optional["ProvinceIndex"] = None

    def __init__(self, assets_dir: Optional[Path] = None):
        self.assets_dir = Path(assets_dir) if assets_dir else ASSETS_DIR
        self._provinces_by_code: Dict[str, Dict[str, Any]] = {}
        self._provinces_by_id: Dict[int, Dict[str, Any]] = {}
        self._search_records: List[Dict[str, Any]] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        prov_path = self.assets_dir / "provinces.json"
        if not prov_path.exists():
            logger.warning("provinces.json not found for index loading", path=str(prov_path))
            return

        with open(prov_path, "r", encoding="utf-8") as f:
            data: Dict[str, Dict[str, Any]] = json.load(f)

        records = []
        for key, p in data.items():
            code = p.get("code", f"PROV-{p['id']}")
            pid = int(p["id"])
            display_name = p.get("display_name") or p["name"]
            search_name = p.get("search_name") or make_search_name(display_name)
            search_country = make_search_name(p.get("country", ""))
            search_aliases = [make_search_name(a) for a in p.get("aliases", []) if a]

            rec = {
                "id": pid,
                "code": code,
                "name": p["name"],
                "country": p.get("country", ""),
                "country_code": p.get("country_code", ""),
                "display_name": display_name,
                "search_name": search_name,
                "search_country": search_country,
                "search_aliases": search_aliases,
                "raw": p
            }
            records.append(rec)
            self._provinces_by_code[code.upper()] = rec
            self._provinces_by_id[pid] = rec

        self._search_records = records
        self._loaded = True
        logger.info("Province index loaded", total_count=len(records))

    def get_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        if not code:
            return None
        return self._provinces_by_code.get(str(code).strip().upper())

    def get_by_id(self, pid: int) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        return self._provinces_by_id.get(int(pid))

    def resolve(self, identifier: str | int) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            res = self.get_by_id(int(identifier))
            if res:
                return res

        code_res = self.get_by_code(str(identifier))
        if code_res:
            return code_res

        # Attempt search match by display_name or name
        q = make_search_name(str(identifier))
        for r in self._search_records:
            if r["search_name"] == q or make_search_name(r["name"]) == q:
                return r

        return None

    def search(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        q = make_search_name(query)

        if not q:
            return self._search_records[:limit]

        exact = []
        prefix_name = []
        prefix_country_alias = []
        contains_name = []
        contains_country_alias = []

        for r in self._search_records:
            s_name = r["search_name"]
            s_country = r["search_country"]
            s_aliases = r["search_aliases"]
            code = r["code"].lower()

            if q == s_name or q == code:
                exact.append(r)
            elif s_name.startswith(q) or code.startswith(q):
                prefix_name.append(r)
            elif s_country.startswith(q) or any(a.startswith(q) for a in s_aliases):
                prefix_country_alias.append(r)
            elif q in s_name:
                contains_name.append(r)
            elif q in s_country or any(q in a for a in s_aliases):
                contains_country_alias.append(r)

        results = exact + prefix_name + prefix_country_alias + contains_name + contains_country_alias
        return results[:limit]

_global_index: Optional[ProvinceIndex] = None

def get_province_index() -> ProvinceIndex:
    global _global_index
    if _global_index is None:
        _global_index = ProvinceIndex()
    return _global_index

async def province_autocomplete(ctx: discord.AutocompleteContext) -> List[discord.OptionChoice]:
    """Py-cord autocomplete callback for province command options."""
    query = ctx.value or ""
    index = get_province_index()
    matches = index.search(query, limit=25)
    choices = [
        discord.OptionChoice(name=p["display_name"][:100], value=p["code"])
        for p in matches
    ]
    return choices
