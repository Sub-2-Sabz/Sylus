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

## Phase 4: Turn Engine & Automated Processing (Completed)
- [x] In-memory `next_turn_at` timer with no database polling loops (`sylus/engine/scheduler.py`).
- [x] Idempotent turn processing using compare-and-set (CAS) on `turn_number` (`sylus/engine/turn.py`).
- [x] Sequential catch-up of overdue turns in order on startup or wake.
- [x] Per-turn map post and summary embed generator.
- [x] Full database snapshot export and state restoration service.
- [x] Admin slash commands cog `/admin` (`channels set_map`, `channels set_backup`, `pause`, `resume`, `force_turn`, `backup`, `restore`).
- [x] Fast-forward CLI tool (`python -m sylus.cli fast-forward --turns N`).
- [x] Unit test suite (`tests/test_turn_engine.py`) covering mid-turn crash rollback, overlapping instances, 5 overdue turns catch-up, no duplicate turns, snapshot export/restore, pause/resume, and CLI fast-forward.

## Phase 5: Nations & Economy (Completed)
- [x] `/nation create` command (name, leader, capital province, color, flag, government type, ideology, starting policy; enforced 1 nation per user constraint).
- [x] Government types & national titles system with custom leader and state titles.
- [x] Policies system with cooldowns, transition costs, and economic multipliers.
- [x] Building construction system (construction turns, upkeep, slot caps per province, terrain bonuses, demolition/upgrades).
- [x] Complete 13-resource production chain table (money, wood, lead, iron, steel, coal, oil, gasoline, aluminum, munitions, uranium, plutonium, research_points).
- [x] Laffer-style tax revenue curve affecting population happiness and growth.
- [x] Commerce income generation scaling with open market policies and stability.
- [x] Storage capacity limits, resource spoilage/decay per turn, and supply/demand inflation market price index.
- [x] Dynamic nation score calculation formula.
- [x] `/nation` dashboards (`info`, `stats`, `economy`, `provinces` with paginated view, `policy`, `build`).
- [x] Externalized all game balance parameters to `/config/*.yaml`.

## Phase 6: Research (Completed)
- [x] Tech trees configured in `/config/research.yaml` (Military, Economy, Community, Industry, Energy, Espionage, Space/Nuclear).
- [x] Component-based military tree (engines, armor, guns, cannons, radar, missiles, avionics, hulls, sonar, propulsion, countermeasures) with levels and prerequisites.
- [x] Database models (`NationTech`, `ResearchQueue`, `TechLicense`) and research service (`sylus/services/research.py`).
- [x] Per-turn research progression allocating RP from resource ledger, auto-unlocking completed techs, and processing license royalties.
- [x] `/research` slash command cog (`tree`, `queue`, `cancel`, `status`, `license`) with visual progress-bar view (`[██████░░░░] 60%`) and tree filtering.

## Phase 7: Trading & Contracts (Completed)
- [x] Direct trade proposals with escrow locking (`/trade offer`, `/trade cancel`, `/trade counter`).
- [x] Public marketplace with buy and sell orders (`/trade market_list`, `/trade market_sell`, `/trade market_buy`, `/trade fill`).
- [x] Partial fills, order expirations, and price history tracking (`/trade price_history`).
- [x] Support for all tradable assets: resources, military units, model blueprints, provinces, and tech licenses.
- [x] Full contract system (`/contract create`, `/contract info`, `/contract sign`, `/contract appeal`, `/contract reputation`).
- [x] All 11 contract types supported with plain-language summaries, duration, obligations, breach conditions, and stated penalties.
- [x] Persistent Py-cord UI views with explicit `custom_id` buttons (`TradePersistentView`, `ContractSignView`) that survive bot restarts.
- [x] Immutable contract storage upon activation (once signed by all parties).
- [x] Automated per-turn contract obligation execution and breach detection with appeal window.
- [x] Admin appeal resolution override (`/admin contract_override`).
- [x] Nation contract fulfillment reputation scoring system.
- [x] Strict balance validation preventing negative balances across all trades, escrow holds, and obligations.

## Phase 8: Diplomacy & Blocs (Unfinished / Future)
- [ ] Alliances, blocs, shared treasuries, auto-created channels, embargoes, UN-style votes.

## Phase 9: Military, Warfare & Covert Ops (Unfinished / Future)
- [ ] Component-based unit designer and production queues.
- [ ] War system with terrain, weather, morale, occupation, peace treaties, and nukes.
- [ ] Espionage and covert ops.
