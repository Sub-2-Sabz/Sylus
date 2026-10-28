import discord
from discord.ext import commands
from sylus.logging import get_logger

logger = get_logger(__name__)

class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.slash_command(name="ping", description="Check bot latency")
    async def ping(self, ctx: discord.ApplicationContext):
        latency_ms = round(self.bot.latency * 1000)
        logger.info("Ping command executed", user_id=ctx.author.id)
        await ctx.respond(f"Pong! Latency: {latency_ms}ms")

def setup(bot: commands.Bot):
    bot.add_cog(PingCog(bot))
