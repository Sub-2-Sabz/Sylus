from aiohttp import web
from sylus.config import config
from sylus.logging import get_logger

logger = get_logger(__name__)

async def handle_health(request: web.Request) -> web.Response:
    if request.method == "HEAD":
        return web.Response(status=200)
    return web.json_response({"status": "ok"})

async def handle_root(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "app": "sylus"})

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health, allow_head=True)
    app.router.add_get("/", handle_root)
    return app

async def run_web_server(host: str | None = None, port: int | None = None) -> web.AppRunner:
    host = host or config.http_host
    port = port if port is not None else config.http_port
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web server started", host=host, port=port)
    return runner
