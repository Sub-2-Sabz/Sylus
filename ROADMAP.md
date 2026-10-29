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

## Phase 8: People, Unrest, Disasters & Narrative Events (Completed)
- [x] Population demographics tracking (workers, soldiers, unemployed, education, crime, health, pollution, corruption, war support).
- [x] Happiness/stability dynamics affected by tax rates, health, education, crime, pollution, corruption.
- [x] Unrest ladder (`normal` -> `protests` -> `riots` -> `civil_war`) with civil war province secession.
- [x] Player responses to unrest (`reforms`, `concessions`, `police_control`, `propaganda`, `military_crackdown`) with costs and trade-offs.
- [x] Config-driven disasters using seeded RNG (all 14 types: epidemic, tornado, hurricane, earthquake, tsunami, flood, drought, wildfire, volcano, famine, industrial accident, nuclear accident, terrorism, economic crash).
- [x] Epidemic spread along active trade links and province borders.
- [x] Disaster damage mitigation (hospitals, infrastructure, insurance, early warning).
- [x] Narrative events with multi-choice options and stat trade-offs.
- [x] Visual disaster zone markers overlaid on turn map rendering.
- [x] Slash command cogs `/people`, `/disasters`, `/event`.

## Phase 9: Diplomacy & Blocs (Unfinished / Future)
- [ ] Alliances, blocs, shared treasuries, auto-created channels, embargoes, UN-style votes.

## Phase 9A: Military Components & Stat Calculator (Completed)
- [x] Defined all 13 unit categories and component slots in `/config/military.yaml`.
- [x] Implemented pure stat calculator computing attack, defense, speed, range, fuel use, stealth, detection, reliability, crew, production cost, upkeep, build time.
- [x] Enforced research technology requirements for selected components.
- [x] Created `UnitDesign` SQLAlchemy model and Alembic migration for saved named models.
- [x] Comprehensive test suite for military designer (`tests/test_military.py`).

## Phase 9B: Military Designer UI & Blueprint Licensing (Completed)
- [x] Multi-step Py-cord UI view (`DesignerWizardView`) with category Select menu and component Select menus (<= 25 options per select, <= 5 action rows per view).
- [x] Live computed stats, production cost, upkeep, and build time updates on component selections.
- [x] Save modal (`SaveDesignModal`) prompting for custom model design name and enforcing research requirements.
- [x] Saved model persistence in database (`UnitDesign`).
- [x] `/design` slash command group (`create`, `list`, `info`, `delete`, `license`).
- [x] Integration with existing marketplace and escrow system for `model_blueprint` asset trading and blueprint cloning.
- [x] Comprehensive unit test suite (`tests/test_designer_ui.py`).

## Phase 9C: Military Production & Logistics (Completed)
- [x] Unit production queues at factories, shipyards, and airbases with strict province facility capacity limits.
- [x] Upkeep, gasoline fuel consumption, and munitions ammunition consumption per formation.
- [x] Manpower recruitment and soldier training (`/military train`).
- [x] Morale dynamics and passive experience gain per military formation.
- [x] Fuel and ammo supply line status tracking and resupply actions (`/military supply`).
- [x] Fog of War intel system obfuscating enemy forces, designs, and strengths unless spied on.
- [x] Espionage spy missions (`/military spy`) lifting Fog of War for a duration.
- [x] Slash command group `/military` (`build`, `queue`, `cancel`, `forces`, `train`, `supply`, `inspect`, `spy`).
- [x] Database models (`MilitaryProductionQueue`, `MilitaryFormation`, `NationIntel`) and Alembic migration.
- [x] Comprehensive unit test suite (`tests/test_military_logistics.py`).

## Phase 10A: War Core & Combat Resolution (Completed)
- [x] War declarations with valid Casus Belli, war slots validation, score range limits, and unprovoked stability/reputation penalties.
- [x] Beige protection & recovery periods preventing war declarations.
- [x] Turn-based Action Points (AP) refill (+12 AP/turn up to max 12) and fatigue decay.
- [x] All 7 core war actions (`ground_attack`, `air_strike`, `naval_attack`, `missile_launch`, `airlift`, `blockade`, `ceasefire_offer`).
- [x] Probabilistic stat-based combat resolution with victory tiers (`Immense Triumph`, `Moderate Success`, `Pyrrhic`, `Failure`).
- [x] Fully modular config-driven combat modifiers (`/config/war.yaml`) for terrain, weather, season, supply, morale, fatigue, experience, tech gap, air superiority, naval control, radar, fortifications, home-field bonus, and war support.
- [x] Per-round war log embed generator and slash command group `/war` (`declare`, `action`, `ceasefire`, `list`, `info`, `log`).
- [x] Comprehensive test suite for independent combat modifiers and war core engine (`tests/test_war.py`).

## Phase 10B: Occupation, Peace Treaties & Nukes (Completed)
- [x] Province capture with occupation progress, insurgency dynamics, and revolt handling (`sylus/services/war_occupation.py`).
- [x] Infrastructure destruction, building damage, and port blockades with trade penalties (`PortBlockade`).
- [x] War support exhaustion auto-surrender and capital capture forced surrender (`trigger_forced_surrender`).
- [x] Ceasefires and formal peace treaties with enforced terms: reparations, territory transfers, tech licensing, demilitarization (`PeaceTreaty`, `sylus/services/peace_treaty.py`).
- [x] Strategic nuclear weapons: tech & resource requirements (Uranium/Plutonium), delivery system requirements, air-defense interception rolls, devastation, fallout disaster zones, and global reputation penalties (`sylus/services/war_nukes.py`).
- [x] War-front rendering on world map with occupied province markers and legend (`mode="war"` in `MapRenderer`).
- [x] Slash command group updates (`/war peace_offer`, `/war peace_accept`, `/war occupation`, `/war map`).
- [x] Comprehensive test suite for Phase 10B (`tests/test_war_phase10b.py`).

## Phase 11: Espionage, Blocs & World Life (Unfinished / Future)
- [ ] Alliances, blocs, shared treasuries, embargoes, UN-style votes.
- [ ] Espionage, sabotage, cyberattacks, coup attempts.
- [ ] NPC factions, global events, and news feed.
