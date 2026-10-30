import asyncio
import signal
import sys
import time
from typing import Any

from sylus.config import config
from sylus.logging import setup_logging, get_logger, log_memory_usage
from sylus.web.server import run_web_server, update_health_cache
from sylus.db.base import get_session

logger = get_logger(__name__)


async def check_and_run_migrations() -> None:
    """Checks whether the database is already at Alembic head before attempting upgrade."""
    t_start = time.perf_counter()
    logger.info("Checking database migration status...")
    loop = asyncio.get_running_loop()

    def _get_alembic_info():
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script_dir.get_current_head()
        return alembic_cfg, head_rev

    alembic_cfg, head_revision = await loop.run_in_executor(None, _get_alembic_info)

    is_head = False
    try:
        async with get_session() as session:
            from sqlalchemy import text
            res = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            row = res.fetchone()
            if row and row[0] == head_revision:
                is_head = True
    except Exception:
        is_head = False

    if is_head:
        t_duration = time.perf_counter() - t_start
        logger.info(
            "Database is already at Alembic head revision. Skipping migrations.",
            head=head_revision,
            duration_seconds=round(t_duration, 4),
        )
        return

    def _run_migrations():
        from alembic import command
        command.upgrade(alembic_cfg, "head")

    try:
        logger.info("Database migration required, upgrading to head...", head=head_revision)
        await loop.run_in_executor(None, _run_migrations)
        t_duration = time.perf_counter() - t_start
        logger.info(
            "Database migrations completed successfully",
            duration_seconds=round(t_duration, 4),
        )
    except Exception as e:
        logger.error("Database migrations failed", error=str(e))
        raise


async def background_sync_provinces() -> None:
    """Runs province DB seeding in the background after web server startup."""
    try:
        t_start = time.perf_counter()
        async with get_session() as session:
            from sylus.services.seed_world import sync_provinces_db
            synced = await sync_provinces_db(session)
        t_duration = time.perf_counter() - t_start
        logger.info(
            "Background province DB sync completed",
            synced_count=synced,
            duration_seconds=round(t_duration, 4),
        )
    except Exception as e:
        logger.error("Background province DB sync failed", error=str(e))


async def start_bot_with_backoff(bot: Any, stop_event: asyncio.Event) -> None:
    token = config.discord_token
    if not token:
        logger.warning("DISCORD_TOKEN is not configured. Skipping Discord bot startup.")
        update_health_cache(discord_status="disconnected")
        await stop_event.wait()
        return

    initial_backoff = float(config.get("bot.reconnect_initial_backoff", 5))
    max_backoff = float(config.get("bot.reconnect_max_backoff", 300))
    backoff_factor = float(config.get("bot.reconnect_backoff_factor", 2))

    current_backoff = initial_backoff

    while not stop_event.is_set():
        try:
            logger.info("Connecting Discord bot...")
            update_health_cache(discord_status="connecting")
            start_task = asyncio.create_task(bot.start(token))
            stop_task = asyncio.create_task(stop_event.wait())

            done, pending = await asyncio.wait(
                [start_task, stop_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()

            if stop_event.is_set():
                logger.info("Stop event received, closing Discord bot connection.")
                update_health_cache(discord_status="disconnected")
                if hasattr(bot, "turn_scheduler"):
                    await bot.turn_scheduler.stop()
                await bot.close()
                break

            if start_task.exception():
                exc = start_task.exception()
                raise exc

            current_backoff = initial_backoff
        except asyncio.CancelledError:
            logger.info("Bot execution cancelled.")
            update_health_cache(discord_status="disconnected")
            if hasattr(bot, "turn_scheduler"):
                await bot.turn_scheduler.stop()
            await bot.close()
            break
        except Exception as exc:
            import discord
            is_rate_limit = False
            retry_after_sec = current_backoff

            if isinstance(exc, discord.HTTPException) and exc.status == 429:
                is_rate_limit = True
                if hasattr(exc, "retry_after") and exc.retry_after:
                    retry_after_sec = float(exc.retry_after)
                elif hasattr(exc, "response") and exc.response:
                    headers = getattr(exc.response, "headers", {})
                    if "Retry-After" in headers:
                        retry_after_sec = float(headers["Retry-After"])

            if is_rate_limit or "429" in str(exc):
                status_state = "blocked_waiting"
                retry_after_sec = max(retry_after_sec, current_backoff)
            else:
                status_state = "connecting"

            update_health_cache(discord_status=status_state)
            logger.error(
                "Discord bot disconnected with error. Retrying with backoff...",
                error=str(exc),
                status_state=status_state,
                backoff_seconds=retry_after_sec,
            )
            if hasattr(bot, "turn_scheduler"):
                await bot.turn_scheduler.stop()
            await bot.close()
            try:
                await asyncio.sleep(retry_after_sec)
            except asyncio.CancelledError:
                break
            current_backoff = min(current_backoff * backoff_factor, max_backoff)


async def main():
    t_startup_start = time.perf_counter()
    setup_logging()
    log_memory_usage("Startup baseline")
    logger.info("Starting Sylus application")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def handle_signal(sig_name):
        logger.info(f"Received signal {sig_name}, initiating graceful shutdown...")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_signal, sig.name)
        except NotImplementedError:
            pass

    # 1. Create bot instance (lightweight)
    t0 = time.perf_counter()
    from sylus.bot.bot import create_bot
    bot = create_bot()
    logger.info("Bot instance created", duration_seconds=round(time.perf_counter() - t0, 4))

    # 2. Start Web Server immediately (takes < 1 second)
    t0 = time.perf_counter()
    web_runner = await run_web_server(bot=bot)
    logger.info("Web server and /health endpoint online", duration_seconds=round(time.perf_counter() - t0, 4))

    # 3. Run Database Migrations (cheap head check)
    t0 = time.perf_counter()
    try:
        await check_and_run_migrations()
        logger.info("Database migration check complete", duration_seconds=round(time.perf_counter() - t0, 4))
    except Exception as e:
        logger.critical("Aborting startup due to migration failure.", error=str(e))
        await web_runner.cleanup()
        sys.exit(1)

    # 4. Schedule background province DB sync (non-blocking)
    asyncio.create_task(background_sync_provinces())

    total_cold_start = time.perf_counter() - t_startup_start
    log_memory_usage("Startup initialization complete")
    logger.info("Cold start complete. Exposing health server.", total_startup_seconds=round(total_cold_start, 4))

    # 5. Start Discord Bot with Reconnect Backoff & Turn Catch-up
    try:
        await start_bot_with_backoff(bot, stop_event)
    finally:
        logger.info("Shutting down web server")
        await web_runner.cleanup()
        logger.info("Sylus shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
