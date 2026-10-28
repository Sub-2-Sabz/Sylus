# Project: SYLUS — A Politics & War–style Nation Simulation Bot (Discord, Py-cord, $0 hosting)

You are a senior full-stack/game engineer working inside Google Jules. Build **Sylus**, a persistent, turn-based nation-simulation game in the style of *Politics & War (PnW)*, played through a Discord bot on a real-Earth map. Work in small phases, one pull request per task. Before coding anything big, keep `ARCHITECTURE.md` and `DECISIONS.md` up to date. When a decision is ambiguous, pick a sensible default, record it in `DECISIONS.md`, and keep going instead of stopping to ask.

## 0. Rules for working as Jules (read first, follow always)

- **Small tasks only.** Each task must touch a handful of files. Never leave a task half finished: if the work is too big, finish a coherent slice, say what remains in the PR description, and list the next step in `ROADMAP.md`.
- **Keep files small.** Hard limit of about 400 lines per Python file. Split big systems into modules (one cog per game system, plus separate `services/`, `models/`, `engine/` modules). Never create one giant file.
- **Always run the tests** (`pytest`) before finishing and paste a short test summary into the PR description. Tests must pass **without** a Discord token, without internet, and without a real Postgres (use SQLite in tests). If you could not run something, say so plainly instead of claiming it works.
- **Never put secrets in the repo.** Tokens, database URLs, and keys come from environment variables. Provide `.env.example` only.
- **Do not fake or stub** a feature and call it done. If something is a placeholder, mark it `TODO` in code and list it in `ROADMAP.md`.
- **Do not add paid services or dependencies.** Everything must work at $0/month.
- The human owner is on a phone and is not an expert: every setup step you document must be copy-paste simple.

## Hard requirements

1. **Py-cord only** (PyPI package `py-cord`, imported as `discord`). **Never use discord.py**, and never install both (they share the `discord` namespace and conflict).
2. **Everything runs at $0/month** (see Section 15 for the exact free setup).
3. **The bot must survive on free hosting that sleeps when idle**, kept awake by UptimeRobot and a Cloudflare Worker pinging a health URL (Section 15).
4. **Low resources:** assume the host has roughly 512 MB of RAM and a fraction of a CPU (check the host's current free-tier specs and note them in `DECISIONS.md`). Design every feature to fit.

---

## 1. Tech stack (defaults — change only with a reason, and document it)

- **Language:** Python 3.12 with **Py-cord 2.x (latest stable)**. Use `discord.Bot`/`commands.Bot`, `@bot.slash_command` / `SlashCommandGroup`, `discord.Option` with autocomplete, `discord.ui.View` / `Button` / `Select`, `discord.ui.Modal`, `ctx.defer()` + `ctx.respond()`/`followup`, `discord.ext.tasks`, `discord.ext.pages`, and **Cogs** loaded with `bot.load_extension`.
- **Web server:** a tiny `aiohttp` server running in the **same process and event loop** as the bot, listening on the port from the `PORT` environment variable. It exposes `/` and `/health` (see Section 15 for exact behavior) and `/internal/turn` (secret-protected).
- **DB:** SQLAlchemy 2.x (async) + Alembic migrations, database-agnostic through `DATABASE_URL`. **Production: a free hosted PostgreSQL (Neon)**. **Tests and local dev: SQLite.** The hosted free database scales to zero when idle and has monthly compute-hour and storage caps, so: use short-lived connections (`NullPool` or a tiny pool), keep queries lean, and **never touch the database from `/health` or from a polling loop** (Section 2).
- **File storage:** a storage interface with a local-disk implementation. Rendered maps are sent straight to Discord as `discord.File`, so no object storage is needed. The host's disk is **ephemeral** (wiped on every restart or redeploy), so never keep game state on disk.
- **Backups (free):** a scheduled job exports the important tables as compressed JSON/SQL and uploads it to a **private Discord backup channel** as an attachment (split or prune to respect the attachment size limit). Provide `/admin backup` and a documented `/admin restore` procedure.
- **Map rendering (memory-safe):** **Do not load GeoPandas, Shapely, or Cartopy at runtime.** A one-time build script (`scripts/build_world.py`, run by the developer/Jules, using Natural Earth data) produces compact committed assets: a province-ID raster (for example a 4096×2048 `uint16` array saved as a compressed `.npz`/PNG), a precomputed border-line overlay, a province table (JSON), and an adjacency list. At runtime, per turn, only **recolor** the ID raster through a NumPy palette lookup, draw capitals/fronts/disaster markers with Pillow, add the legend, downscale for Discord, and cache. Keep peak RAM small and output images under about 1–2 MB.
- **Scheduler:** in-process, event-driven (Section 2). Turn processing must be **idempotent and transactional** (guarded by a DB lock or compare-and-set on the turn number).
- **Config:** all balance numbers in YAML/JSON under `/config` (buildings, costs, yields, unit parts, disasters, terrain, weather). **No magic numbers in code.**
- **Testing:** pytest with a deterministic seeded RNG. Provide a CLI to fast-forward N turns. Mock Discord objects so game logic is testable without a live bot.
- **Deploy:** `Dockerfile` (small, slim base, non-root user), `.env.example`, `render.yaml` (Render blueprint), `workers/keepalive/` (Cloudflare Worker), and a README with exact copy-paste setup steps.

---

## 2. Core rules

- **One turn every 2 hours** (configurable, default 7200s). A global turn counter and a `next_turn_at` timestamp are stored in the DB.
- **Do not poll the database to see if a turn is due.** Read `next_turn_at` once at startup (and after each turn), keep it in memory, and use an in-process timer (`asyncio` sleep-until or `discord.ext.tasks` with a cheap in-memory check) to wake at the right time. Only touch the DB when a turn is actually due or a user runs a command. This lets the free database sleep and saves its monthly compute hours.
- **Catch-up on wake/restart:** on startup, if one or more turns are overdue (the host slept, restarted, or redeployed), process them **in order, safely, without duplicating** any turn, then post a single combined summary and the latest map. Missed turns must never double-apply or half-apply, even if two instances briefly overlap during a redeploy.
- **One nation per Discord user** (DB unique constraint). Anti-multi-account tools for admins (flag shared guilds/join patterns, manual review).
- Every turn the bot processes: economy → research → population/happiness → disasters → unrest → contracts → war rounds → border updates, then **renders the world map and posts it to a configured channel** with a turn summary embed (turn number, top nations, wars, major events, disasters).
- Admin commands: set map channel, announcement channel, backup channel, turn speed, pause/resume, force turn, rollback to last snapshot.
- Take a **snapshot every N turns** (exported to the private Discord backup channel) and keep an **audit log** of every state-changing action (who, what, when).
- **Restart-safe:** all state lives in the DB, buttons/views are **persistent** (fixed `custom_id`s, re-registered on startup), and graceful shutdown on `SIGTERM` closes the Discord client cleanly.
- **Low-resource friendly:** paginate large queries, cache expensive renders, avoid loading the whole world into memory per command.

---

## 3. The world map (Earth)

- Divide Earth into **provinces/regions** from Natural Earth admin-1 (merge/simplify so the total is manageable, e.g., ~400–1500). Each province has: terrain type (plains, forest, mountain, desert, jungle, arctic, urban, coastal), climate zone, base resource deposits, population capacity, coordinates, adjacency list (land + sea lanes).
- Players **found a nation** by claiming an unowned province (starter capital). Nations expand by **claiming adjacent unowned land** (cost + cooldown), **conquering** in war, **buying/trading** provinces, or **ceding** them via treaty.
- Borders change when ownership changes. Each nation has a unique color/flag (color picker + optional flag upload, moderated).
- Map posted every turn: political map with borders, capital stars, war fronts highlighted, disaster zones overlaid, and a legend. Also `/map nation`, `/map region`, `/map war`, `/map resources`, `/map terrain` (on-demand, rate-limited).
- Support alliances/blocs on the map (shared hatch color or outline).

---

## 4. Resources & economy

Resources: **money, wood, lead, iron, steel, coal, oil, gasoline, aluminum, munitions, uranium, plutonium, research points (RP)**.

Production chains (all configurable):

| Output | Building | Inputs |
|---|---|---|
| Wood | Sawmill | — (needs forest terrain bonus) |
| Lead | Lead mine | — |
| Iron | Iron mine | — |
| Coal | Coal mine | — |
| Steel | Iron burner/steel mill | iron + coal |
| Oil | Oil well | — |
| Gasoline | Refinery | oil |
| Aluminum | Aluminum mine/smelter | — (power/coal optional) |
| Munitions | Munitions factory | lead (+ optional steel/coal) |
| Uranium / Plutonium | Uranium mine / Plutonium reactor-mine | — (heavily regulated, high cost, high risk) |
| Research points | Research center | money/electricity upkeep |
| Money | Tax, trade, commerce (shops, banks, ports, tourism), resource sales | — |

Rules:
- Buildings cost resources + money, have **construction time (in turns)**, **upkeep**, **pollution**, **employment**, and a **slot cap** per province (based on population/infrastructure). Allow upgrades (levels) and demolition.
- Production depends on **province deposits, terrain, infrastructure, workforce, stability, power, and policies**. Missing inputs = reduced output (never negative).
- **Taxes:** adjustable rate with a Laffer-style curve — high taxes raise income but lower happiness and growth.
- **Commerce:** commerce buildings + trade routes + ports give money, scaled by trade openness and stability.
- **Storage limits** (warehouses, silos), **spoilage/decay** for some goods; **blockades** reduce imports/exports.
- Nuclear materials require special facilities; uranium/plutonium have security requirements and can trigger incidents.
- **Inflation/market price indexing** so prices respond to global supply and demand.

---

## 5. Research

- Research points from research centers, universities, and policies; spend them in **tech trees**: **Military, Economy, Community (society/health/education/infrastructure), Industry, Energy, Espionage, Space/Nuclear**.
- The Military tree is **component-based**: engines, armor, guns, cannons, radar, missiles, avionics, hulls, sonar, propulsion, countermeasures, etc. Each component has levels and prerequisites. A component must be researched before it can be used in a design.
- Unlocks can be **traded or licensed** between players (tech-sharing treaties with royalty terms).
- Visual tech-tree command with progress bars, filter by tree, and a research queue.

---

## 6. Military: custom design system

Unit categories: **infantry/soldier loadouts, air defense, fighters, bombers, helicopters, tanks, APCs/IFVs, artillery, missiles, warships (corvette → carrier), submarines, drones, nuclear delivery systems** (extensible).

- A **Designer** (Py-cord modals + select menus, optional web dashboard) lets players pick: chassis/hull, engine, armor, main weapon(s), secondary weapons, radar/sensors, countermeasures, special features, crew size. Respect Discord limits (modals: 5 inputs; selects: 25 options) with multi-step views.
- Each design computes stats: attack, defense, speed, range, fuel use, stealth, detection, reliability, crew, **production cost (resources + money), upkeep, build time**. Cost scales with component quality.
- Designs are saved as **named models** (e.g., "Falcon-IV"). Each model is an individually tradable asset type; units carry the model ID. Players can **sell/trade/license a blueprint** or individual units.
- **Production:** build queues at factories/shipyards/airbases with capacity limits. Units need munitions, gasoline, upkeep, and trained manpower.
- **Logistics:** fuel and ammo supply lines; units out of supply lose effectiveness.
- **Training/experience** and **morale** per formation.
- **Fog of war / intel:** enemy designs and strengths are hidden unless spied on.

---

## 7. War (PnW-style, with environment)

- **Declaration:** requires casus belli or incurs a stability/reputation cost. War slots (offensive/defensive) and range limits like PnW. Beige/recovery periods after a loss.
- **Each turn** players act using **Action/Military Points** (ground attack, air strike, naval attack, missile launch, nuclear strike, airlift, blockade, espionage, sabotage, ceasefire offers). Points refill each turn.
- **Resolution:** probabilistic + stat-based, with **victory tiers** (Immense Triumph / Moderate Success / Pyrrhic / Failure). Compute losses to units, infrastructure, population, and loot.
- **Modifiers (modular, config-driven):** terrain (mountains favor defenders, jungle penalizes armor, desert hits fuel, arctic hits equipment), **weather** (storms ground aircraft, fog reduces air/naval accuracy, mud slows armor), season/climate, **supply, morale, fatigue, experience, tech gap, air superiority, naval control, radar coverage, fortifications, home-field bonus**, war support at home.
- **Objectives:** capture provinces (occupation progress, resistance/insurgency), destroy infrastructure, blockade ports, win by exhausting enemy morale/war support or capturing the capital.
- **Peace:** ceasefires and treaties with terms (reparations, territory, tech, demilitarization), enforced automatically.
- **Nuclear weapons:** extremely costly; need research + uranium/plutonium + a delivery system; can be intercepted; cause fallout zones, a global reputation penalty, and devastation.
- Per-round war log embeds with a map snippet of the front line.

---

## 8. Trading & contracts

- **Market:** player-to-player offers for any resource, unit, model blueprint, province, or tech license. Direct trade (`/trade offer @user`) with escrow, plus a public **marketplace** with buy/sell orders and price-history charts.
- **Escrow:** assets locked until both sides confirm. Support partial fills, expiry, counter-offers.
- **Contracts:** Trade agreement, Non-aggression pact, Defense pact, Alliance, Military aid, Loan/debt (with interest), Tech-sharing, Resource supply (recurring per turn), Tribute/vassalage, Peace treaty, Custom.
  - Each defines: parties, duration, obligations per turn/one-time, **breach conditions**, and **stated penalty** (fine, asset seizure, tariff, sanction, temporary ban, **permanent ban** — whatever the contract states, within server rules).
  - **Automated enforcement:** recurring obligations execute each turn; breaches trigger the stated penalty, with an **arbitration/appeal window** and admin override. Banned = removed from the game, assets handled per a configurable policy (frozen/redistributed/abandoned).
  - **Both parties sign** via persistent buttons, after a plain-language summary. Contracts are stored immutably with timestamps.
  - **Reputation scores** from contract fulfillment shown on nation profiles.
- **Diplomacy:** alliances/blocs with ranks, optional shared treasuries, auto-created bloc channels, embargoes, sanctions, UN-style global votes.

---

## 9. People, happiness, protests, disasters

- Each nation has **population** (workers, soldiers, unemployed, education), **happiness/stability**, **crime**, **health**, **education**, **pollution**, **infrastructure**, **corruption**, **war support**.
- **Unrest:** low happiness → **protests** → **riots** → **civil war/secession** (provinces can break away as rebel states or NPC factions). Players respond with **reforms, concessions, police/riot control (costs money, may anger more), propaganda, or military crackdown**, each with trade-offs.
- **Disasters** (seeded RNG, regionally appropriate): epidemics/pandemics (spread via trade links and borders), tornadoes, hurricanes, earthquakes, tsunamis, floods, droughts, wildfires, volcanic eruptions, famine, industrial accidents, nuclear accidents, terrorism, economic crashes. They kill population, destroy buildings/infrastructure/stockpiles, reduce output, and cost money. Mitigation via infrastructure, hospitals, preparedness research, insurance, early warning, and international aid.
- Random **narrative events** with choices that modify stats.
- Disaster zones appear on the turn map.

---

## 10. Nation management (player-facing)

- `/nation create`: name, leader name, capital province, color, flag, government type, ideology, starting policy.
- **National titles:** custom leader titles and government names (moderated), plus unlockable titles via achievements.
- **Policies** (PnW-style toggles/sliders with trade-offs): economic, war (pirate, turtle, blitzkrieg, guardian…), domestic, foreign, social, energy, immigration, conscription, press freedom, tax rates. Changes have **cooldowns** and transition costs.
- **Government types** (democracy, monarchy, republic, junta, theocracy, communist, etc.) with distinct bonuses/penalties and elections/succession events.
- **Development:** roads/rail/ports/airports/power plants (coal, oil, nuclear, solar, wind, hydro) and **national projects/wonders** (Space Program, Intelligence Agency, Missile Defense), one per nation, expensive, long build.
- **Dashboard:** `/nation info`, `stats`, `economy`, `military`, `provinces` with paginated embeds. Leaderboards: score, GDP, military, land, research.
- **Nation score** formula (like PnW) for war ranges.

---

## 11. Espionage & covert ops

Spy network, intel gathering, sabotage, assassinations of leaders (rare), propaganda ops, coup attempts, cyberattacks on infrastructure. Counter-intel research reduces success. Config-driven odds.

---

## 12. Bot UX & admin

- Everything via **slash commands + buttons + modals + select menus** (Py-cord); paginated embeds; ephemeral replies for private info; autocomplete for nations/resources/models. Always `defer()` anything that might take over 3 seconds.
- **Tutorial/onboarding** flow, `/help` by category, `/guide` for beginners, and a sandbox practice mode.
- **Notifications** (per-user toggles) for war declarations, trade offers, contracts, disasters, protests, turn summaries.
- **Admin tools:** pause, rollback, give/take resources, ban/unban, edit nations, spawn disasters, hot-reload balance config, audit log, backup/restore, season reset (new world each season with hall of fame).
- **Anti-abuse:** command cooldowns, transaction validation, row locks against race conditions, **no negative balances ever**.
- **Moderation:** filters for nation names, flags, contract text. Localization-ready strings.
- `/status` admin command: uptime, current turn, next turn time, DB latency, last render time, last backup time.
- Optional: lightweight web dashboard (FastAPI + HTMX) for the unit designer, map viewer, and market charts.

---

## 13. NPCs & world life

- **NPC nations/factions** fill unclaimed land, trade, and act as rebels, scaling with player activity.
- **Global events:** bloc formation, resource shortages, oil crises, global pandemics, tech breakthroughs, space race milestones.
- **News feed:** a "Sylus Daily" post each turn.
- **Seasons & achievements** with leaderboards.

---

## 14. Delivery plan (one phase = one or more small Jules tasks, one PR each)

1. **Foundation:** repo structure, config system, DB models/migrations, Py-cord bot skeleton with cog loader, aiohttp `/health`, logging, audit log, tests, `.env.example`, Dockerfile.
2. **Free hosting + keep-alive:** `render.yaml`, the Cloudflare Worker in `workers/keepalive/`, the README setup guide for Neon + Render + UptimeRobot + Cloudflare Worker, a "hello world" bot that stays online.
3. **World assets:** `scripts/build_world.py`, province raster/table/adjacency committed, runtime map renderer, per-turn map post.
4. **Turn engine:** in-memory timer, catch-up logic, idempotency, snapshots, Discord backups, restart-safety tests.
5. **Nations & economy:** creation, provinces, buildings, resources, taxes, storage, market prices.
6. **Research & tech tree.**
7. **Trading, escrow, marketplace, contracts + enforcement.**
8. **People, unrest, disasters, events.**
9. **Military designer, production, logistics.**
10. **War system with terrain/weather/morale, occupation, peace, nukes.**
11. **Espionage, alliances, diplomacy, NPCs, news.**
12. **Admin tools, anti-abuse, tutorial, polish, docs, low-resource load testing.**

For each task: write unit tests, update docs, and put a short summary of what's done and what's next in the PR description. Prioritize **correctness, data integrity, and balance configurability** over flashy features. When the design is ambiguous, choose the option closest to Politics & War's behavior and note it in `DECISIONS.md`.

---

## 15. Free hosting + keep-alive design (Render + Neon + UptimeRobot + Cloudflare Worker)

**Why this setup:** Py-cord needs a permanent connection to Discord. Free web hosts put apps to sleep when no one visits them, and a sleeping bot is offline. So the bot runs as a free **Render web service** (it must answer HTTP), and two free pingers visit its `/health` URL every few minutes so it never sleeps: **UptimeRobot** (primary) and a **Cloudflare Worker with a Cron Trigger** (backup, offset in time). Game data lives in a free **Neon Postgres** database.

**Facts to document in the README (and tell the user to re-check, because free tiers change):**
- Render free web services spin down after about 15 minutes with no inbound HTTP traffic. Outbound traffic (the Discord connection) does not count as activity. They have a monthly free instance-hour allowance and a bandwidth cap, use an ephemeral disk, and are slower to start after a sleep.
- UptimeRobot's free plan checks every 5 minutes. That is frequent enough to stay under Render's 15-minute sleep window.
- Neon's free tier has small storage, monthly compute-hour caps, and scales to zero after a few minutes of inactivity.
- Keeping a free service awake with pings can change or break at any time, or conflict with a provider's terms. The README must say this plainly, and the bot must still work correctly if it does go to sleep (catch-up logic, Section 2).

### 15.1 The `/health` endpoint (exact behavior)
- `GET /health` returns HTTP 200 with a tiny JSON body: `{"status":"ok","turn":<cached turn>,"discord":"connected|connecting"}`.
- It must be **fast and cheap: no database queries, no map rendering, no disk reads.** Use only values already cached in memory. (If it touched the DB, every ping would wake the free database and burn its compute hours.)
- Support both `GET` and `HEAD` (UptimeRobot may use either).
- Return HTTP 200 even while the bot is still reconnecting to Discord. Include the Discord state in the JSON body so a keyword monitor can check it if the owner wants.
- Also serve `GET /` with a short plain-text "Sylus is running".
- `/internal/turn` requires an `INTERNAL_SECRET` header and is only for manual or emergency triggers.

### 15.2 Render setup (`render.yaml` + Dockerfile)
- Provide a `render.yaml` blueprint defining one **free web service** built from the `Dockerfile`, with `healthCheckPath: /health`, `PORT` handled automatically, and environment variables declared as `sync: false` placeholders for `DISCORD_TOKEN`, `DATABASE_URL`, and `INTERNAL_SECRET`.
- The bot and web server start together from one entrypoint (`python -m sylus`). On startup: run migrations, load config, start the web server **first** (so Render sees an open port quickly), then connect to Discord, then run turn catch-up.
- Handle `SIGTERM`: stop accepting work, finish or roll back the in-flight turn transaction, close the Discord client, exit.
- Respect Discord connect/identify rate limits: on crash loops use exponential backoff so repeated restarts do not get the bot token throttled.

### 15.3 Cloudflare Worker keep-alive (you write all of this code)
Create `workers/keepalive/` containing:
- `worker.js`: a **single, self-contained, copy-paste-able file** (no npm packages) that handles the `scheduled` event, reads `HEALTH_URL` from `env`, calls `fetch(env.HEALTH_URL, { method: "GET", headers: { "User-Agent": "sylus-keepalive" } })` with a timeout (use `AbortController`, about 30 seconds, because a cold Render start can take a minute), logs the status code, and optionally (if the `ALERT_WEBHOOK_URL` variable exists) posts a short message to that Discord webhook **only when** the check fails twice in a row. It must also answer normal `fetch` requests with a short plain-text status so the owner can open the Worker URL to test it.
- `wrangler.jsonc` with `"name": "sylus-keepalive"`, `"main": "worker.js"`, a current `compatibility_date`, `"triggers": { "crons": ["2-59/5 * * * *"] }` (every 5 minutes, offset by 2 minutes from UptimeRobot's schedule), and a `vars` block with a placeholder `HEALTH_URL`.
- `README.md` with **two copy-paste setup methods, written for someone on a phone with no coding experience**:
  1. **Dashboard method (easiest):** create a Worker in the Cloudflare dashboard, open its code editor, paste in `worker.js`, deploy, then add the `HEALTH_URL` variable and a Cron Trigger under the Worker's settings, and open the Worker's URL once to confirm it works.
  2. **GitHub method (optional):** connect the repo to Cloudflare Workers builds with the root directory set to `workers/keepalive`.
- Do not require a credit card or paid plan; stay inside Cloudflare's free Workers limits.

### 15.4 UptimeRobot setup (documentation only; the owner does this in the website)
Write a step-by-step section in the main README: create a free UptimeRobot account, add an **HTTP(s) monitor** pointing at `https://<render-service>.onrender.com/health`, set the interval to 5 minutes, optionally add a keyword monitor for `"ok"`, and add the owner's Discord or email as an alert contact. Explain that UptimeRobot and the Cloudflare Worker are two independent pingers so the bot stays awake if one of them fails.

### 15.5 Neon setup (documentation only)
README steps: create a free Neon project, copy the pooled connection string, convert it to the async SQLAlchemy URL format the code expects (document the exact format and any `sslmode` quirks), and paste it into Render as `DATABASE_URL`.

### 15.6 Cost and reliability notes for the README
- State the expected monthly cost: $0, with the limits that matter (Render instance hours and bandwidth, Neon compute hours and storage, Discord attachment size).
- Keep outbound bandwidth low (cache and compress map images).
- Include a troubleshooting table: bot offline, `/health` timing out, Neon limit reached, Render out of hours, duplicate turns after redeploy, and what to do for each.
- Include an "upgrade path" paragraph: if the free setup becomes unreliable, moving to a small always-on host only requires changing where the Docker image runs, because the code does not depend on keep-alive pings to be correct.

---

**Definition of done:** following only the README, a person on a phone can set up GitHub, Neon, Render, UptimeRobot, and the Cloudflare Worker at $0, bring the Py-cord bot online, run `/nation create`, build, research, trade, sign a contract, design a unit, declare war, and see the updated Earth map posted automatically every 2 hours. The bot stays awake through the pings, survives sleeps and redeploys without losing or duplicating a turn, backs itself up to a private Discord channel, and 100+ simulated turns pass in tests without errors or economy-breaking exploits.
