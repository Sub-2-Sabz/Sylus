import pytest
from sylus.bot.bot import create_bot

def test_bot_initialization_and_cogs():
    bot = create_bot()
    assert "PingCog" in bot.cogs
    cog = bot.get_cog("PingCog")
    assert cog is not None
