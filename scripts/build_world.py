import os
import sys
import json
import unicodedata
import urllib.request
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sylus.config import config

ASSETS_DIR = Path(config.get("map.assets_dir", "sylus/assets/world"))
CANVAS_WIDTH = config.get("map.canvas_width", 2048)
CANVAS_HEIGHT = config.get("map.canvas_height", 1024)

ADMIN_1_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson"
ADMIN_0_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"

def normalize_text(text: str) -> str:
    """Returns normalized NFC unicode text."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text).strip())

def make_search_name(text: str) -> str:
    """Returns lowercase, accent-free search string."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_bytes = nfkd.encode("ASCII", "ignore")
    return ascii_bytes.decode("utf-8").lower().strip()

def latlon_to_pixel(lon: float, lat: float, width: int, height: int):
    """Converts (longitude, latitude) to canvas (x, y) pixel coordinates."""
    x = int((lon + 180.0) / 360.0 * (width - 1))
    y = int((90.0 - lat) / 180.0 * (height - 1))
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))

def geom_to_pixels(geom, width: int, height: int):
    """Converts Shapely geometry coordinates to list of polygon pixel coordinate lists."""
    polys = []
    if geom.geom_type == 'Polygon':
        geoms = [geom]
    elif geom.geom_type == 'MultiPolygon':
        geoms = list(geom.geoms)
    else:
        return polys

    for poly in geoms:
        exterior = poly.exterior.coords
        pixel_ring = [latlon_to_pixel(x, y, width, height) for x, y in exterior]
        if len(pixel_ring) >= 3:
            polys.append(pixel_ring)
    return polys

def determine_terrain_and_climate(lat: float, lon: float, is_coastal: bool, area: float) -> tuple[str, str]:
    """Determines terrain and climate based on coordinates and geography."""
    abs_lat = abs(lat)
    if abs_lat > 66.0:
        climate = "polar"
        terrain = "arctic"
    elif abs_lat > 50.0:
        climate = "continental"
        terrain = "forest"
    elif abs_lat > 23.5:
        climate = "temperate"
        if is_coastal:
            terrain = "coastal"
        elif 15.0 < lon < 50.0 and 15.0 < lat < 35.0:
            terrain = "desert"
            climate = "arid"
        else:
            terrain = "plains"
    else:
        if 15.0 < lon < 50.0 and 10.0 < lat < 30.0:
            climate = "arid"
            terrain = "desert"
        else:
            climate = "tropical"
            terrain = "jungle" if not is_coastal else "coastal"

    return terrain, climate

def generate_sample_world(target_dir: Path = None, width: int = None, height: int = None):
    """Generates a synthetic compact sample world asset set for testing."""
    out_dir = Path(target_dir) if target_dir else ASSETS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    w = width if width else CANVAS_WIDTH
    h = height if height else CANVAS_HEIGHT

    grid_rows, grid_cols = 5, 6
    cell_h, cell_w = h // grid_rows, w // grid_cols

    raster = np.zeros((h, w), dtype=np.uint16)
    provinces = {}
    adjacency = {}

    terrains = ["plains", "forest", "mountain", "desert", "jungle", "coastal", "urban", "arctic"]
    climates = ["temperate", "tropical", "arid", "continental", "polar"]

    prov_id = 1
    for r in range(grid_rows):
        for c in range(grid_cols):
            if prov_id > 30:
                break
            if r == 0 or r == grid_rows - 1 or c == 0 or c == grid_cols - 1:
                if (r + c) % 2 == 0:
                    prov_id += 1
                    continue

            y_start, y_end = r * cell_h, (r + 1) * cell_h
            x_start, x_end = c * cell_w, (c + 1) * cell_w

            raster[y_start:y_end, x_start:x_end] = prov_id

            capital_x = x_start + cell_w // 2
            capital_y = y_start + cell_h // 2

            terrain = terrains[(prov_id - 1) % len(terrains)]
            climate = climates[(prov_id - 1) % len(climates)]
            country = f"Region {(prov_id - 1) // 5 + 1}"
            name = f"Province {prov_id}"
            display_name = name
            code = f"SMP-{prov_id}"

            provinces[str(prov_id)] = {
                "id": prov_id,
                "code": code,
                "name": name,
                "country": country,
                "country_code": "SMP",
                "display_name": display_name,
                "search_name": make_search_name(display_name),
                "aliases": [f"P{prov_id}"],
                "terrain": terrain,
                "climate": climate,
                "deposits": {"gold": 10 * prov_id, "iron": 5 * prov_id},
                "population_capacity": 100000 + prov_id * 5000,
                "capital_coords": [capital_x, capital_y],
                "centroid_latlon": [0.0, 0.0]
            }
            prov_id += 1

    for pid in provinces:
        p_num = int(pid)
        neighbors = []
        for other_id in provinces:
            o_num = int(other_id)
            if p_num != o_num and abs(p_num - o_num) in (1, grid_cols):
                neighbors.append(o_num)
        adjacency[pid] = neighbors

    border_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    diff_h = (raster[:-1, :] != raster[1:, :])
    diff_w = (raster[:, :-1] != raster[:, 1:])
    border_color = tuple(config.get("map.default_colors.border", [30, 30, 30])) + (255,)

    y_indices, x_indices = np.where(diff_h)
    for y, x in zip(y_indices, x_indices):
        if raster[y, x] != 0 or raster[y + 1, x] != 0:
            border_img.putpixel((x, y), border_color)

    y_indices, x_indices = np.where(diff_w)
    for y, x in zip(y_indices, x_indices):
        if raster[y, x] != 0 or raster[y, x + 1] != 0:
            border_img.putpixel((x, y), border_color)

    np.savez_compressed(out_dir / "province_raster.npz", raster=raster)
    border_img.save(out_dir / "border_overlay.png")

    with open(out_dir / "provinces.json", "w", encoding="utf-8") as f:
        json.dump(provinces, f, ensure_ascii=False, indent=2)

    with open(out_dir / "adjacency.json", "w", encoding="utf-8") as f:
        json.dump(adjacency, f, indent=2)

def build_world():
    import geopandas as gpd
    from shapely.geometry import Point

    print("Downloading Natural Earth data...")
    print(f"Fetching Admin-1: {ADMIN_1_URL}")
    gdf_adm1 = gpd.read_file(ADMIN_1_URL)

    print(f"Fetching Admin-0: {ADMIN_0_URL}")
    gdf_adm0 = gpd.read_file(ADMIN_0_URL)

    print(f"Loaded {len(gdf_adm1)} Admin-1 features and {len(gdf_adm0)} Admin-0 features.")

    adm1_adm0_codes = set(gdf_adm1["adm0_a3"].dropna().unique())
    adm0_rows_to_add = []
    for idx, row in gdf_adm0.iterrows():
        adm0_code = row.get("ADM0_A3") or row.get("SOV_A3") or row.get("ISO_A2")
        country_name = row.get("ADMIN") or row.get("NAME")
        if adm0_code and adm0_code not in adm1_adm0_codes:
            adm0_rows_to_add.append(row)

    print(f"Adding {len(adm0_rows_to_add)} missing countries from Admin-0 as single-province records.")

    raw_provinces = []

    for idx, row in gdf_adm1.iterrows():
        code = row.get("adm1_code")
        if not code or str(code).strip() == "":
            code = f"{row.get('iso_a2', 'XX')}-{idx}"
        code = str(code).strip()

        name = normalize_text(row.get("name") or row.get("name_en") or row.get("name_ascii") or "Unknown")
        country = normalize_text(row.get("admin") or row.get("sovereignt") or "Unknown")
        country_code = str(row.get("iso_a2") or row.get("adm0_a3") or "XX").upper()

        aliases_raw = [
            row.get("name_alt"), row.get("name_local"), row.get("name_ascii"),
            row.get("code_hasc"), row.get("postal")
        ]
        aliases = []
        for a in aliases_raw:
            if a is not None:
                sa = str(a).strip()
                if sa and sa.lower() not in ("nan", "none", "null") and sa != name:
                    norm_a = normalize_text(sa)
                    if norm_a not in aliases:
                        aliases.append(norm_a)

        geom = row.geometry
        centroid = geom.centroid if geom else Point(0, 0)
        area = geom.area if geom else 1.0

        prov_type = normalize_text(row.get("type_en") or row.get("type") or "")

        raw_provinces.append({
            "code": code,
            "name": name,
            "country": country,
            "country_code": country_code,
            "type": prov_type,
            "aliases": aliases,
            "geom": geom,
            "centroid": centroid,
            "area": area
        })

    for row in adm0_rows_to_add:
        code = f"ADM0-{row.get('ADM0_A3') or row.get('ISO_A2') or idx}"
        country_name = normalize_text(row.get("ADMIN") or row.get("NAME") or "Unknown")
        country_code = str(row.get("ISO_A2") or row.get("ADM0_A3") or "XX").upper()
        geom = row.geometry
        centroid = geom.centroid if geom else Point(0, 0)
        area = geom.area if geom else 1.0

        raw_provinces.append({
            "code": code,
            "name": country_name,
            "country": country_name,
            "country_code": country_code,
            "aliases": [],
            "geom": geom,
            "centroid": centroid,
            "area": area
        })

    name_counts = {}
    for p in raw_provinces:
        n = p["name"]
        name_counts[n] = name_counts.get(n, 0) + 1

    # First pass: display_name = name or "Name, Country"
    disp_counts = {}
    for p in raw_provinces:
        n = p["name"]
        c = p["country"]
        if name_counts[n] > 1 or n == c:
            disp = f"{n}, {c}"
        else:
            disp = n
        p["display_name"] = disp
        disp_counts[disp] = disp_counts.get(disp, 0) + 1

    # Second pass: disambiguate duplicates within same country using type or code
    final_disp_counts = {}
    for p in raw_provinces:
        disp = p["display_name"]
        if disp_counts[disp] > 1:
            ptype = p.get("type")
            if ptype:
                disp = f"{disp} ({ptype})"
            else:
                disp = f"{disp} ({p['code']})"
        p["display_name"] = disp
        final_disp_counts[disp] = final_disp_counts.get(disp, 0) + 1

    # Final fallback if still duplicate
    for p in raw_provinces:
        disp = p["display_name"]
        if final_disp_counts[disp] > 1:
            p["display_name"] = f"{disp} [{p['code']}]"

    provinces_dict = {}
    adjacency_dict = {}

    width, height = CANVAS_WIDTH, CANVAS_HEIGHT
    raster_img = Image.new("I;16", (width, height), 0)
    draw_raster = ImageDraw.Draw(raster_img)

    print(f"Rasterizing {len(raw_provinces)} provinces onto {width}x{height} canvas...")

    for pid_int, p in enumerate(raw_provinces, start=1):
        code = p["code"]
        name = p["name"]
        country = p["country"]
        display_name = p["display_name"]

        search_name = make_search_name(display_name)
        centroid = p["centroid"]
        lon, lat = centroid.x, centroid.y
        cx, cy = latlon_to_pixel(lon, lat, width, height)
        geom = p["geom"]
        is_coastal = False

        terrain, climate = determine_terrain_and_climate(lat, lon, is_coastal, p["area"])

        deposits = {
            "iron": int(10 + (pid_int * 7) % 50),
            "coal": int(5 + (pid_int * 13) % 40),
            "wood": int(20 + (pid_int * 11) % 60),
            "money": 1000
        }
        pop_cap = int(max(50000, min(50000000, p["area"] * 10000000)))

        provinces_dict[str(pid_int)] = {
            "id": pid_int,
            "code": code,
            "name": name,
            "country": country,
            "country_code": p["country_code"],
            "display_name": display_name,
            "search_name": search_name,
            "aliases": p["aliases"],
            "terrain": terrain,
            "climate": climate,
            "deposits": deposits,
            "population_capacity": pop_cap,
            "capital_coords": [cx, cy],
            "centroid_latlon": [round(lat, 4), round(lon, 4)]
        }

        poly_pixels = geom_to_pixels(geom, width, height)
        for poly in poly_pixels:
            draw_raster.polygon(poly, fill=pid_int)

    raster_array = np.array(raster_img, dtype=np.uint16)

    print("Computing province adjacencies...")
    adj_sets = {pid_int: set() for pid_int in range(1, len(raw_provinces) + 1)}

    diff_h = (raster_array[:-1, :] != raster_array[1:, :])
    y1, x1 = np.where(diff_h)
    for y, x in zip(y1, x1):
        p1 = int(raster_array[y, x])
        p2 = int(raster_array[y + 1, x])
        if p1 > 0 and p2 > 0 and p1 != p2:
            adj_sets[p1].add(p2)
            adj_sets[p2].add(p1)

    diff_w = (raster_array[:, :-1] != raster_array[:, 1:])
    y2, x2 = np.where(diff_w)
    for y, x in zip(y2, x2):
        p1 = int(raster_array[y, x])
        p2 = int(raster_array[y, x + 1])
        if p1 > 0 and p2 > 0 and p1 != p2:
            adj_sets[p1].add(p2)
            adj_sets[p2].add(p1)

    for pid_int, neighbors in adj_sets.items():
        if not neighbors:
            pinfo = provinces_dict[str(pid_int)]
            lat1, lon1 = pinfo["centroid_latlon"]
            closest = []
            for other_id, oinfo in provinces_dict.items():
                oid = int(other_id)
                if oid == pid_int:
                    continue
                lat2, lon2 = oinfo["centroid_latlon"]
                dist = (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2
                closest.append((dist, oid))
            closest.sort(key=lambda item: item[0])
            for d, oid in closest[:3]:
                adj_sets[pid_int].add(oid)
                adj_sets[oid].add(pid_int)

    for pid_int, neighbors in adj_sets.items():
        adjacency_dict[str(pid_int)] = sorted(list(neighbors))

    print("Generating border overlay image...")
    border_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    border_color = tuple(config.get("map.default_colors.border", [30, 30, 30])) + (255,)

    y_indices, x_indices = np.where(diff_h)
    for y, x in zip(y_indices, x_indices):
        if raster_array[y, x] != 0 or raster_array[y + 1, x] != 0:
            border_img.putpixel((x, y), border_color)

    y_indices, x_indices = np.where(diff_w)
    for y, x in zip(y_indices, x_indices):
        if raster_array[y, x] != 0 or raster_array[y, x + 1] != 0:
            border_img.putpixel((x, y), border_color)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ASSETS_DIR / "province_raster.npz", raster=raster_array)
    border_img.save(ASSETS_DIR / "border_overlay.png")

    with open(ASSETS_DIR / "provinces.json", "w", encoding="utf-8") as f:
        json.dump(provinces_dict, f, ensure_ascii=False, indent=2)

    with open(ASSETS_DIR / "adjacency.json", "w", encoding="utf-8") as f:
        json.dump(adjacency_dict, f, indent=2)

    print(f"Successfully built world assets in {ASSETS_DIR}!")

def main():
    try:
        build_world()
    except Exception as e:
        print(f"Error building world: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
