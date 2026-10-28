# Sylus Project Roadmap

## Phase 1: Foundation (Completed)
- [x] Repository structure setup with pyproject.toml and requirements.txt (Py-cord, SQLAlchemy asyncio, Alembic, aiohttp, structlog).
- [x] Externalized configuration loader (`/config` YAML files & `.env.example`).
- [x] Async SQLAlchemy database models: `GlobalState`, `Nation`, `Province`, `ResourceLedger`, and `AuditLog`.
- [x] Alembic migration pipeline setup.
- [x] Structured JSON logging with `structlog`.
- [x] `aiohttp` web server with `/health` (GET/HEAD) and `/` (GET) endpoints without DB dependency.
- [x] Py-cord bot skeleton with dynamic cog loader and `/ping` slash command.
- [x] Dockerfile and documentation (`ARCHITECTURE.md`, `DECISIONS.md`, `ROADMAP.md`).
- [x] Pytest suite using async SQLite.

## Phase 2: Free Hosting & Keep-Alive Infrastructure (Completed)
- [x] Render Blueprint configuration (`render.yaml`) for Docker web service deployment.
- [x] Single entrypoint (`sylus/main.py`) lifecycle ordering:
  1. `aiohttp` web server starts first (listening on `PORT`/`HTTP_PORT`).
  2. Database migrations (`alembic upgrade head`) run programmatically.
  3. Discord bot starts with exponential backoff reconnect loop.
  4. Graceful SIGTERM/SIGINT signal handling for clean shutdown.
- [x] Cloudflare Worker keep-alive infrastructure in `workers/keepalive/` (`worker.js`, `wrangler.jsonc`, `README.md`) pinging `/health` every 5 minutes.
- [x] Comprehensive phone-friendly deployment setup guide and Section 15.6 troubleshooting table in root `README.md`.
- [x] Unit tests for `/health` (GET and HEAD) and Cloudflare Worker config/script structure.

## Phase 3: World Assets & Map Rendering (Completed)
- [x] Build script `scripts/build_world.py` converting Natural Earth admin-1 data or synthetic fallback into small committed world assets (`province_raster.npz`, `border_overlay.png`, `provinces.json`, `adjacency.json`). Note: If internet or runtime GIS dependencies (GeoPandas/Shapely) are unavailable, `scripts/build_world.py` outputs a clear notice and commits a compact synthetic world asset set so tests and the bot run seamlessly.
- [x] Runtime memory-safe map renderer (`sylus/map/renderer.py`) using NumPy palette recoloring and Pillow drawing (no runtime GeoPandas, Shapely, or Cartopy).
- [x] Map slash command group `/map` (`world`, `terrain`, `province`).
- [x] Map configuration (`config/map.yaml`) storing all rendering and palette balance variables.
- [x] Unit test suite covering world building, map rendering, and `/map` slash commands (`tests/test_map.py`).

## Phase 4: Nation & Territory Management (Unfinished / Future)
- [ ] Nation registration slash command (`/register`).
- [ ] Territory/province claiming logic and boundaries.
- [ ] Resource income generation per turn.
- [ ] Nation profile and status slash commands (`/nation status`).

## Phase 5: Economic & Trade Ledger (Unfinished / Future)
- [ ] Trade agreement proposal and execution between nations.
- [ ] Market system and resource exchange.
- [ ] Detailed resource ledger transaction logs.

## Phase 6: Turn Engine & Automated Processing (Unfinished / Future)
- [ ] Turn progression engine and background scheduler.
- [ ] Event hooks for turn processing (upkeep, resource distribution, population growth).
- [ ] Notification engine for Discord channel alerts on turn change.

## Phase 7: Warfare & Diplomacy (Unfinished / Future)
- [ ] Troop recruitment and army management.
- [ ] Battle resolution system and casualties log.
- [ ] Alliance and treaty system.
