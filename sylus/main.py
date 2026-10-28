import asyncio
import signal
from sylus.config import config
from sylus.logging import setup_logging, get_logger
from sylus.web.server import run_web_server
from sylus.bot.bot import create_bot

logger = get_logger(__name__)

async def main():
    setup_logging()
    logger.info("Starting Sylus application")

    web_runner = await run_web_server()

    bot = create_bot()
    token = config.discord_token

    if not token:
        logger.warning("DISCORD_TOKEN is not configured. Running web server only.")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    else:
        try:
            await bot.start(token)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await bot.close()

    logger.info("Shutting down web server")
    await web_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
