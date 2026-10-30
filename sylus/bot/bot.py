import os
import pkgutil
import importlib
from typing import Any
import discord
from discord.ext import commands
from sylus.config import config
from sylus.engine.scheduler import TurnScheduler
from sylus.logging import get_logger

logger = get_logger(__name__)


import hashlib
from pathlib import Path

HASH_FILE_PATH = Path("sylus/assets/last_synced_commands_hash.txt")


def calculate_command_definitions_hash(bot: commands.Bot) -> str:
    """Computes a stable hash of all registered application commands and options."""
    cmds_data = []
    for cmd in sorted(bot.pending_application_commands, key=lambda c: c.name):
        cmd_repr = {
            "name": cmd.name,
            "description": getattr(cmd, "description", ""),
            "options": [
                {
                    "name": getattr(opt, "name", ""),
                    "description": getattr(opt, "description", ""),
                    "required": getattr(opt, "required", False),
                }
                for opt in getattr(cmd, "options", [])
            ],
        }
        cmds_data.append(cmd_repr)

    serialized = str(cmds_data).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


async def sync_commands_if_changed(bot: commands.Bot, force: bool = False) -> bool:
    """Syncs commands with Discord API only if definition hash changed or force=True."""
    current_hash = calculate_command_definitions_hash(bot)
    last_hash = ""

    if HASH_FILE_PATH.exists():
        try:
            last_hash = HASH_FILE_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            last_hash = ""

    if not force and current_hash == last_hash:
        logger.info("Slash command definitions unchanged. Skipping bot.sync_commands().", hash=current_hash[:8])
        return False

    logger.info("Syncing slash commands with Discord API...", force=force, new_hash=current_hash[:8])
    await bot.sync_commands()

    try:
        HASH_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        HASH_FILE_PATH.write_text(current_hash, encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to save command hash file", error=str(e))

    return True


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.members = False
    intents.presences = False
    intents.message_content = False

    bot = commands.Bot(
        command_prefix="/",
        intents=intents,
        member_cache_flags=discord.MemberCacheFlags.none(),
        max_messages=None,
        chunk_guilds_at_startup=False,
        auto_sync_commands=False,
    )

    bot._configured_channel_cache = {}

    def get_configured_channel(channel_id: int | None) -> Any:
        if not channel_id:
            return None
        if channel_id in bot._configured_channel_cache:
            ch = bot._configured_channel_cache[channel_id]
            if ch:
                return ch
        ch = bot.get_channel(channel_id)
        if ch:
            bot._configured_channel_cache[channel_id] = ch
        return ch

    bot.get_configured_channel = get_configured_channel

    from sylus.services.outbound_queue import OutboundMessageQueue
    outbound_queue = OutboundMessageQueue(bot=bot)
    bot.outbound_queue = outbound_queue

    scheduler = TurnScheduler(bot=bot)
    bot.turn_scheduler = scheduler

    @bot.event
    async def on_ready():
        from sylus.web.server import update_health_cache
        logger.info("Discord bot logged in", user=str(bot.user), user_id=bot.user.id if bot.user else None)
        update_health_cache(discord_status="connected")

        if not getattr(bot, "_commands_synced", False):
            try:
                await sync_commands_if_changed(bot)
            except Exception as e:
                logger.error("Failed to check/sync commands on ready", error=str(e))
            bot._commands_synced = True

        if not getattr(bot, "_outbound_queue_started", False):
            bot.outbound_queue.start()
            bot._outbound_queue_started = True

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
