import asyncio
import signal
import sys
from alembic import command
from alembic.config import Config as AlembicConfig
from sylus.config import config
from sylus.logging import setup_logging, get_logger
from sylus.web.server import run_web_server
from sylus.bot.bot import create_bot

logger = get_logger(__name__)

async def run_migrations_async() -> None:
    logger.info("Starting database migrations")
    loop = asyncio.get_running_loop()

    def _run_migrations():
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)
        command.upgrade(alembic_cfg, "head")

    try:
        await loop.run_in_executor(None, _run_migrations)
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error("Database migrations failed", error=str(e))
        raise

async def start_bot_with_backoff(stop_event: asyncio.Event) -> None:
    token = config.discord_token
    if not token:
        logger.warning("DISCORD_TOKEN is not configured. Skipping Discord bot startup.")
        await stop_event.wait()
        return

    initial_backoff = float(config.get("bot.reconnect_initial_backoff", 5))
    max_backoff = float(config.get("bot.reconnect_max_backoff", 300))
    backoff_factor = float(config.get("bot.reconnect_backoff_factor", 2))

    current_backoff = initial_backoff

    while not stop_event.is_set():
        bot = create_bot()
        try:
            logger.info("Connecting Discord bot...")
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
                await bot.close()
                break

            # If start_task completed or failed
            if start_task.exception():
                exc = start_task.exception()
                raise exc

            current_backoff = initial_backoff
        except asyncio.CancelledError:
            logger.info("Bot execution cancelled.")
            await bot.close()
            break
        except Exception as exc:
            logger.error(
                "Discord bot disconnected with error. Retrying in seconds...",
                error=str(exc),
                backoff_seconds=current_backoff,
            )
            await bot.close()
            try:
                await asyncio.sleep(current_backoff)
            except asyncio.CancelledError:
                break
            current_backoff = min(current_backoff * backoff_factor, max_backoff)

async def main():
    setup_logging()
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

    # 1. Start Web Server first
    web_runner = await run_web_server()

    # 2. Run Database Migrations
    try:
        await run_migrations_async()
    except Exception as e:
        logger.critical("Aborting startup due to migration failure.", error=str(e))
        await web_runner.cleanup()
        sys.exit(1)

    # 3. Start Discord Bot with Reconnect Backoff
    try:
        await start_bot_with_backoff(stop_event)
    finally:
        logger.info("Shutting down web server")
        await web_runner.cleanup()
        logger.info("Sylus shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())
