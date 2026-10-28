import os
import pkgutil
import importlib
import discord
from discord.ext import commands
from sylus.config import config
from sylus.engine.scheduler import TurnScheduler
from sylus.logging import get_logger

logger = get_logger(__name__)


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="/", intents=intents)

    scheduler = TurnScheduler(bot=bot)
    bot.turn_scheduler = scheduler

    @bot.event
    async def on_ready():
        logger.info("Discord bot logged in", user=str(bot.user), user_id=bot.user.id if bot.user else None)
        if not getattr(bot, "_scheduler_started", False):
            scheduler.start()
            bot._scheduler_started = True

    load_cogs(bot)
    return bot


def load_cogs(bot: commands.Bot) -> None:
    from sylus.bot import cogs
    cogs_path = cogs.__path__
    prefix = cogs.__name__ + "."

    for _, name, is_pkg in pkgutil.iter_modules(cogs_path, prefix):
        if not is_pkg:
            try:
                bot.load_extension(name)
                logger.info("Loaded cog extension", extension=name)
            except Exception as e:
                logger.error("Failed to load cog extension", extension=name, error=str(e))
