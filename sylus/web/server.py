import typing
from aiohttp import web
from sylus.config import config
from sylus.logging import get_logger

logger = get_logger(__name__)

# Cached state for zero-DB-query /health endpoint
_health_cache: dict[str, typing.Any] = {
    "status": "ok",
    "turn": 0,
    "discord": "connecting",
}


def update_health_cache(turn: int | None = None, discord_status: str | None = None) -> None:
    if turn is not None:
        _health_cache["turn"] = turn
    if discord_status is not None:
        _health_cache["discord"] = discord_status


async def handle_health(request: web.Request) -> web.Response:
    if request.method == "HEAD":
        return web.Response(status=200)
    return web.json_response(_health_cache)


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="Sylus is running", content_type="text/plain")


async def handle_internal_turn(request: web.Request) -> web.Response:
    secret = request.headers.get("X-Internal-Secret") or request.headers.get("INTERNAL_SECRET")
    expected_secret = config.internal_secret
    if not expected_secret or secret != expected_secret:
        return web.json_response({"error": "Unauthorized"}, status=401)

    bot = request.app.get("bot")
    if bot and hasattr(bot, "turn_scheduler") and bot.turn_scheduler:
        result = await bot.turn_scheduler.force_turn()
        if result:
            return web.json_response({
                "status": "ok",
                "message": f"Turn {result.turn_number} executed successfully.",
                "turn": result.turn_number,
            })
        return web.json_response({"status": "skipped", "message": "Turn processing returned no result (paused or lock issue)."})
    return web.json_response({"status": "error", "message": "Bot turn scheduler not available."}, status=503)


def create_app(bot: typing.Any = None) -> web.Application:
    app = web.Application()
    if bot is not None:
        app["bot"] = bot
    app.router.add_get("/health", handle_health, allow_head=True)
    app.router.add_get("/", handle_root)
    app.router.add_post("/internal/turn", handle_internal_turn)
    return app

async def run_web_server(host: str | None = None, port: int | None = None, bot: typing.Any = None) -> web.AppRunner:
    host = host or config.http_host
    port = port if port is not None else config.http_port
    app = create_app(bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web server started", host=host, port=port)
    return runner
