import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sylus.config import config
from sylus.logging import get_logger

logger = get_logger(__name__)

ASSETS_DIR = Path(config.get("map.assets_dir", "sylus/assets/world"))
CANVAS_WIDTH = config.get("map.canvas_width", 1024)
CANVAS_HEIGHT = config.get("map.canvas_height", 512)
CACHE_SIZE = config.get("map.cache_max_size", 32)


class MapRenderer:
    """Runtime map renderer using NumPy palette vector recoloring and Pillow."""

    def __init__(self, assets_dir: Optional[Path] = None):
        self.assets_dir = Path(assets_dir) if assets_dir else ASSETS_DIR
        self._raster: Optional[np.ndarray] = None
        self._border_overlay: Optional[Image.Image] = None
        self._provinces: Dict[str, Dict[str, Any]] = {}
        self._adjacency: Dict[str, List[int]] = {}
        self._load_assets()

    def _load_assets(self) -> None:
        raster_path = self.assets_dir / "province_raster.npz"
        border_path = self.assets_dir / "border_overlay.png"
        prov_path = self.assets_dir / "provinces.json"
        adj_path = self.assets_dir / "adjacency.json"

        if not raster_path.exists():
            raise FileNotFoundError(f"Missing map asset: {raster_path}")

        npz_file = np.load(raster_path)
        self._raster = npz_file["raster"]

        if border_path.exists():
            self._border_overlay = Image.open(border_path).convert("RGBA")

        if prov_path.exists():
            with open(prov_path, "r", encoding="utf-8") as f:
                self._provinces = json.load(f)

        if adj_path.exists():
            with open(adj_path, "r", encoding="utf-8") as f:
                self._adjacency = json.load(f)

    @property
    def provinces(self) -> Dict[str, Dict[str, Any]]:
        return self._provinces

    @property
    def adjacency(self) -> Dict[str, List[int]]:
        return self._adjacency

    def get_province(self, province_id: int) -> Optional[Dict[str, Any]]:
        return self._provinces.get(str(province_id))

    def render_map(
        self,
        nation_owners: Optional[Dict[int, Tuple[int, int, int]]] = None,
        capitals: Optional[List[Tuple[int, int]]] = None,
        mode: str = "political",
        legend_title: str = "Sylus World Map",
        nation_names: Optional[Dict[Tuple[int, int, int], str]] = None,
        disaster_zones: Optional[Dict[int, str]] = None,
        occupied_provinces: Optional[Dict[int, int]] = None,
    ) -> io.BytesIO:
        """Renders world map image and returns PNG BytesIO stream."""
        if self._raster is None:
            raise RuntimeError("MapRenderer raster not loaded")

        height, width = self._raster.shape
        ocean_rgb = config.get("map.default_colors.ocean", [30, 40, 60])
        unclaimed_rgb = config.get("map.default_colors.unclaimed_land", [180, 180, 180])
        occ_color = config.get("war.map.occupied_stripe_color", [200, 50, 50])
        max_prov = int(self._raster.max()) if self._raster.size > 0 else 0

        # Build palette array: shape (max_prov + 1, 3)
        palette = np.zeros((max_prov + 1, 3), dtype=np.uint8)
        palette[0] = ocean_rgb

        if mode == "terrain":
            terrain_colors = config.get("map.terrain_colors", {})
            for pid_str, pinfo in self._provinces.items():
                pid = int(pid_str)
                if pid <= max_prov:
                    t_type = pinfo.get("terrain", "plains")
                    color = terrain_colors.get(t_type, unclaimed_rgb)
                    palette[pid] = color
        else:  # Political or War mode
            for pid_str in self._provinces:
                pid = int(pid_str)
                if pid <= max_prov:
                    palette[pid] = unclaimed_rgb

            if nation_owners:
                for pid, color in nation_owners.items():
                    if pid <= max_prov:
                        palette[pid] = color

            if occupied_provinces:
                for pid in occupied_provinces:
                    if pid <= max_prov:
                        palette[pid] = occ_color

        # Perform vectorized recolor via array indexing
        rgb_array = palette[self._raster]
        img = Image.fromarray(rgb_array, mode="RGB").convert("RGBA")

        # Blend border overlay if present
        if self._border_overlay is not None:
            img = Image.alpha_composite(img, self._border_overlay)

        draw = ImageDraw.Draw(img)

        # Draw capital markers
        if capitals:
            r = config.get("map.capital_marker.radius", 5)
            fill_c = tuple(config.get("map.capital_marker.fill_color", [255, 215, 0]))
            out_c = tuple(config.get("map.capital_marker.outline_color", [0, 0, 0]))
            for cx, cy in capitals:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill_c, outline=out_c, width=2)

        # Draw occupied / war front markers
        if occupied_provinces:
            f_r = 6
            for pid in occupied_provinces:
                pinfo = self.get_province(pid)
                if pinfo and "capital_coords" in pinfo:
                    cx, cy = pinfo["capital_coords"]
                    draw.rectangle([cx - f_r, cy - f_r, cx + f_r, cy + f_r], fill=(220, 20, 20, 220), outline=(255, 255, 255), width=2)
                    draw.text((cx - 3, cy - 6), "X", fill=(255, 255, 255))

        # Draw disaster zone markers
        if disaster_zones:
            d_r = 7
            for pid, dtype in disaster_zones.items():
                pinfo = self.get_province(pid)
                if pinfo and "capital_coords" in pinfo:
                    cx, cy = pinfo["capital_coords"]
                    draw.ellipse([cx - d_r, cy - d_r, cx + d_r, cy + d_r], fill=(255, 60, 0, 200), outline=(255, 255, 255), width=2)
                    draw.text((cx - 2, cy - 6), "!", fill=(255, 255, 255))

        # Draw legend if nation_names provided or mode specified
        if mode == "war" and legend_title == "Sylus World Map":
            legend_title = "War Front World Map"
        self._draw_legend(draw, mode, legend_title, nation_names, has_occupations=bool(occupied_provinces))

        output = io.BytesIO()
        img.save(output, format=config.get("map.output_format", "PNG"))
        output.seek(0)
        return output

    def render_region_map(
        self,
        province_id: int | str,
        nation_owners: Optional[Dict[int, Tuple[int, int, int]]] = None,
        capitals: Optional[List[Tuple[int, int]]] = None,
        mode: str = "political",
        margin_pixels: int = 50,
    ) -> Tuple[io.BytesIO, Optional[Dict[str, Any]]]:
        """Renders zoomed region map around a specific province."""
        pinfo = None
        pid = None

        if isinstance(province_id, int) or (isinstance(province_id, str) and province_id.isdigit()):
            pid = int(province_id)
            pinfo = self.get_province(pid)
        else:
            # Search by code or display_name
            from sylus.services.province_search import get_province_index
            rec = get_province_index().resolve(str(province_id))
            if rec:
                pid = rec["id"]
                pinfo = rec["raw"]

        if self._raster is None or pid is None:
            return self.render_map(nation_owners=nation_owners, capitals=capitals, mode=mode), pinfo

        # Full render stream first
        height, width = self._raster.shape
        full_img_stream = self.render_map(nation_owners=nation_owners, capitals=capitals, mode=mode)
        full_img = Image.open(full_img_stream)

        # Locate province bounding box
        y_indices, x_indices = np.where(self._raster == pid)
        if len(y_indices) > 0:
            min_x, max_x = int(x_indices.min()), int(x_indices.max())
            min_y, max_y = int(y_indices.min()), int(y_indices.max())
        elif pinfo and "capital_coords" in pinfo:
            cx, cy = pinfo["capital_coords"]
            min_x, max_x = cx - 30, cx + 30
            min_y, max_y = cy - 30, cy + 30
        else:
            min_x, max_x, min_y, max_y = 0, width, 0, height

        x0 = max(0, min_x - margin_pixels)
        x1 = min(width, max_x + margin_pixels)
        y0 = max(0, min_y - margin_pixels)
        y1 = min(height, max_y + margin_pixels)

        cropped_img = full_img.crop((x0, y0, x1, y1)).convert("RGBA")
        draw = ImageDraw.Draw(cropped_img)

        # Draw label on cropped region
        disp_name = pinfo.get("display_name", pinfo.get("name", f"Province {pid}")) if pinfo else f"Province {pid}"
        if pinfo and "capital_coords" in pinfo:
            cx, cy = pinfo["capital_coords"]
            lx, ly = cx - x0, cy - y0
        else:
            lx, ly = (x1 - x0) // 2, (y1 - y0) // 2

        # Draw label banner
        text_bbox = draw.textbbox((lx, ly), disp_name)
        pad = 4
        banner = [text_bbox[0] - pad, text_bbox[1] - pad, text_bbox[2] + pad, text_bbox[3] + pad]
        draw.rectangle(banner, fill=(20, 20, 25, 220), outline=(255, 215, 0), width=1)
        draw.text((lx, ly), disp_name, fill=(255, 255, 255))

        output = io.BytesIO()
        cropped_img.save(output, format=config.get("map.output_format", "PNG"))
        output.seek(0)
        return output, pinfo

    def _draw_legend(
        self,
        draw: ImageDraw.ImageDraw,
        mode: str,
        legend_title: str,
        nation_names: Optional[Dict[Tuple[int, int, int], str]],
        has_occupations: bool = False,
    ) -> None:
        padding = config.get("map.legend.padding", 10)
        item_h = config.get("map.legend.item_height", 20)
        box_sz = config.get("map.legend.box_size", 14)
        margin = config.get("map.legend.margin", 15)
        bg_c = tuple(config.get("map.default_colors.legend_bg", [20, 20, 25])) + (200,)
        text_c = tuple(config.get("map.default_colors.text", [255, 255, 255]))

        items: List[Tuple[Tuple[int, int, int], str]] = []
        if mode == "terrain":
            t_colors = config.get("map.terrain_colors", {})
            for tname, col in t_colors.items():
                items.append((tuple(col), tname.capitalize()))
        elif nation_names:
            for col, nname in nation_names.items():
                items.append((col, nname))

        if has_occupations:
            occ_c = tuple(config.get("war.map.occupied_stripe_color", [200, 50, 50]))
            items.append((occ_c, "Occupied / Front"))

        if not items:
            return

        box_w = 180
        box_h = padding * 2 + (len(items) + 1) * item_h
        x0, y0 = margin, margin
        x1, y1 = x0 + box_w, y0 + box_h

        draw.rectangle([x0, y0, x1, y1], fill=bg_c, outline=(100, 100, 100))
        draw.text((x0 + padding, y0 + padding), legend_title, fill=text_c)

        curr_y = y0 + padding + item_h
        for col, label in items:
            draw.rectangle([x0 + padding, curr_y, x0 + padding + box_sz, curr_y + box_sz], fill=col, outline=(0, 0, 0))
            draw.text((x0 + padding + box_sz + 8, curr_y), label, fill=text_c)
            curr_y += item_h


@lru_cache(maxsize=CACHE_SIZE)
def get_cached_map_renderer(assets_dir_str: str) -> MapRenderer:
    return MapRenderer(Path(assets_dir_str))
