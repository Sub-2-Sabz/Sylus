# Technical Architecture Decisions (ADR)

## Decision 1: Library Selection for Discord Integration
- **Decision**: Use `py-cord` (>= 2.6.0) instead of standard `discord.py`.
- **Rationale**: Py-cord provides built-in first-class support for application slash commands and active maintenance.

## Decision 2: Asynchronous Database ORM and Migration Framework
- **Decision**: Use `sqlalchemy[asyncio]` (>= 2.0.0) with `aiosqlite` for local dev/testing and `asyncpg` for production, managed by `alembic`.
- **Rationale**: SQLAlchemy 2.0 provides fully async DB capabilities and strong typing. Alembic handles database schema migrations reliably across drivers.

## Decision 3: Zero Magic Numbers & Externalized Configuration
- **Decision**: Put all economic balance variables, resource definitions, and game settings into external `/config` YAML files accessed via `sylus.config.Config`.
- **Rationale**: Ensures clear separation of game design values from application logic, allowing easy tuning without code modifications.

## Decision 4: Web Server Framework & Health Endpoint
- **Decision**: Use `aiohttp` for the web server layer.
- **Rationale**: Lightweight, high performance, and fully asynchronous, integrating smoothly with `asyncio`. Health check endpoints (`/health` and `/`) remain decoupled from DB access to ensure fast monitoring responses.

## Decision 5: Structured Logging
- **Decision**: Use `structlog` for structured JSON logging.
- **Rationale**: JSON logging enables easy parsing and ingestion into log management platforms (ELK, Datadog) and structured context tracking.
