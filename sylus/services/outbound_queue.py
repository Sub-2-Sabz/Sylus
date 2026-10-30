import asyncio
import random
import time
from typing import Any, Optional, Dict, Tuple
import discord
from sylus.logging import get_logger

logger = get_logger(__name__)

# Priorities: 0 = HIGH (e.g. direct replies/interactions), 1 = LOW (notifications, broadcasts)
PRIORITY_HIGH = 0
PRIORITY_LOW = 1


class OutboundMessageItem:
    """Represents a message dispatch task in the central outbound queue."""

    def __init__(
        self,
        target: Any,
        action: str = "send",
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        embeds: Optional[list[discord.Embed]] = None,
        files: Optional[list[discord.File]] = None,
        priority: int = PRIORITY_LOW,
        message_to_edit: Optional[discord.Message] = None,
    ):
        self.target = target
        self.action = action
        self.content = content
        self.embed = embed
        self.embeds = embeds
        self.files = files
        self.priority = priority
        self.message_to_edit = message_to_edit
        self.created_at = time.perf_counter()
        self.future: asyncio.Future = asyncio.get_running_loop().create_future()

    def __lt__(self, other: "OutboundMessageItem") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class OutboundMessageQueue:
    """Central rate-limited outbound message queue for all non-direct command replies."""

    def __init__(
        self,
        bot: Optional[Any] = None,
        rate_per_sec: float = 1.5,
        jitter_range: Tuple[float, float] = (0.02, 0.08),
    ):
        self.bot = bot
        self.rate_per_sec = rate_per_sec
        self.delay_between_messages = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.5
        self.jitter_range = jitter_range
        self._queue: asyncio.PriorityQueue[OutboundMessageItem] = asyncio.PriorityQueue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._blocked_until: float = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Outbound message queue worker started.", rate_per_sec=self.rate_per_sec)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Outbound message queue worker stopped.")

    async def enqueue(
        self,
        target: Any,
        action: str = "send",
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        embeds: Optional[list[discord.Embed]] = None,
        files: Optional[list[discord.File]] = None,
        priority: int = PRIORITY_LOW,
        message_to_edit: Optional[discord.Message] = None,
        wait_for_result: bool = False,
    ) -> Any:
        item = OutboundMessageItem(
            target=target,
            action=action,
            content=content,
            embed=embed,
            embeds=embeds,
            files=files,
            priority=priority,
            message_to_edit=message_to_edit,
        )
        await self._queue.put(item)
        if wait_for_result:
            return await item.future
        return item.future

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                item = await self._queue.get()
                now = time.time()
                if self._blocked_until > now:
                    wait_time = self._blocked_until - now
                    logger.warning("Queue paused for rate-limit cooldown", wait_seconds=wait_time)
                    from sylus.web.server import update_health_cache
                    update_health_cache(discord_status="blocked_waiting")
                    await asyncio.sleep(wait_time)
                    update_health_cache(discord_status="connected")

                success = await self._dispatch_item(item)
                self._queue.task_done()

                # Add rate-limit delay with jitter
                jitter = random.uniform(*self.jitter_range)
                await asyncio.sleep(self.delay_between_messages + jitter)

            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error("Error in outbound queue worker loop", error=str(err))
                await asyncio.sleep(0.5)

    async def _dispatch_item(self, item: OutboundMessageItem) -> bool:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = None
                kwargs: Dict[str, Any] = {}
                if item.content is not None:
                    kwargs["content"] = item.content
                if item.embed is not None:
                    kwargs["embed"] = item.embed
                if item.embeds is not None:
                    kwargs["embeds"] = item.embeds
                if item.files is not None:
                    kwargs["files"] = item.files

                if item.action == "edit" and item.message_to_edit:
                    result = await item.message_to_edit.edit(**kwargs)
                elif item.action in ("send", "dm"):
                    if hasattr(item.target, "send"):
                        result = await item.target.send(**kwargs)
                    else:
                        raise ValueError(f"Target {type(item.target)} has no send() method")

                if not item.future.done():
                    item.future.set_result(result)
                return True

            except discord.HTTPException as http_err:
                if http_err.status == 429:
                    retry_after = getattr(http_err, "retry_after", None)
                    if retry_after is None and hasattr(http_err, "response") and http_err.response:
                        headers = getattr(http_err.response, "headers", {})
                        retry_after = float(headers.get("Retry-After", 2.0))
                    if retry_after is None:
                        retry_after = 2.0

                    self._blocked_until = time.time() + float(retry_after) + 0.1
                    logger.warning("HTTP 429 Rate Limit hit in outbound queue!", retry_after=retry_after, attempt=attempt)
                    from sylus.web.server import update_health_cache
                    update_health_cache(discord_status="blocked_waiting")
                    await asyncio.sleep(float(retry_after) + 0.1)
                    update_health_cache(discord_status="connected")
                    continue
                else:
                    logger.error("HTTP exception in outbound queue dispatch", status=http_err.status, error=str(http_err))
                    if not item.future.done():
                        item.future.set_exception(http_err)
                    return False
            except Exception as exc:
                logger.error("Unexpected error in outbound queue dispatch", error=str(exc))
                if not item.future.done():
                    item.future.set_exception(exc)
                return False

        if not item.future.done():
            item.future.set_exception(RuntimeError("Max retries exceeded due to rate limits"))
        return False
