# Sylus Architecture Document

## Overview
Sylus is a grand strategy bot platform integrated with Discord. It combines a Py-cord Discord bot with an asynchronous SQLAlchemy database layer and an aiohttp web server for health checks and API integration.

## Component Layout

```
sylus/
├── bot/
│   ├── cogs/          # Discord slash command cogs
│   │   └── ping.py    # Sample slash command cog
│   ├── bot.py         # Bot instantiation & dynamic cog loader
│   └── __init__.py
├── db/
│   ├── base.py        # Async SQLAlchemy engine & session factory
│   ├── models.py      # Declarative ORM models
│   └── __init__.py
├── web/
│   ├── server.py      # aiohttp HTTP web server & health checks
│   └── __init__.py
├── config.py          # YAML & environment variable configuration loader
├── logging.py         # Structured JSON logging via structlog
└── main.py            # Async application entrypoint
config/
├── balance.yaml       # Economy & balance settings
├── game_settings.yaml # Game turn & global rules
└── resources.yaml     # Resource definitions
alembic/               # Database migration scripts
tests/                 # Pytest test suite with async SQLite
```

## Database Schema Model (Phase 1)
- **GlobalState**: Tracks global game metadata (`turn_number`, `next_turn_at`, timestamps).
- **Nation**: Represents a player nation tied to a `discord_user_id`.
- **Province**: Represents territorial units with terrain types assigned to a `nation_id`.
- **ResourceLedger**: Tracks resource balances (gold, food, wood, iron) per `nation_id`.
- **AuditLog**: Records system and player actions with details stored as JSON.

## System Interfaces
- **Discord Bot**: Built on Py-cord 2.8+, supporting slash commands and async event handling.
- **Web API**: Built on `aiohttp` listening on port `8080`. Offers `GET /`, `GET /health`, and `HEAD /health` without database dependencies.
