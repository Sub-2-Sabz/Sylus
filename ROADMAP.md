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

## Phase 3: Nation & Territory Management (Unfinished / Future)
- [ ] Nation registration slash command (`/register`).
- [ ] Territory/province claiming logic and boundaries.
- [ ] Resource income generation per turn.
- [ ] Nation profile and status slash commands (`/nation status`).

## Phase 4: Economic & Trade Ledger (Unfinished / Future)
- [ ] Trade agreement proposal and execution between nations.
- [ ] Market system and resource exchange.
- [ ] Detailed resource ledger transaction logs.

## Phase 5: Turn Engine & Automated Processing (Unfinished / Future)
- [ ] Turn progression engine and background scheduler.
- [ ] Event hooks for turn processing (upkeep, resource distribution, population growth).
- [ ] Notification engine for Discord channel alerts on turn change.

## Phase 6: Warfare & Diplomacy (Unfinished / Future)
- [ ] Troop recruitment and army management.
- [ ] Battle resolution system and casualties log.
- [ ] Alliance and treaty system.
