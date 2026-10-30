import asyncio
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Any
import discord
from sqlalchemy.ext.asyncio import AsyncSession

from sylus.config import config
from sylus.db.base import get_session
from sylus.db.models import GlobalState, utc_now
from sylus.engine.turn import get_or_create_global_state, process_single_turn, TurnResult
from sylus.logging import get_logger

logger = get_logger(__name__)


class TurnScheduler:
    """In-memory event-driven turn scheduler with catch-up logic."""

    def __init__(self, bot: Optional[Any] = None, session_factory: Optional[Callable[[], AsyncSession]] = None):
        self.bot = bot
        self.session_factory = session_factory or get_session
        self._task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Turn scheduler started.")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._wake_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Turn scheduler stopped.")

    async def catch_up_overdue_turns(self) -> int:
        """Processes overdue turns in sequential order on startup/wake."""
        processed_count = 0
        max_catchup = int(config.get("turn_engine.max_catchup_turns", 50))

        while self._running or not self._task:
            if processed_count >= max_catchup:
                logger.warning("Reached max catchup turn limit", limit=max_catchup)
                break

            async with self.session_factory() as session:
                state = await get_or_create_global_state(session)
                if state.is_paused:
                    logger.info("Catchup skipped: Global state is paused.")
                    break

                now = utc_now()
                next_turn_dt = state.next_turn_at
                if next_turn_dt is not None and next_turn_dt.tzinfo is None:
                    next_turn_dt = next_turn_dt.replace(tzinfo=timezone.utc)

                if next_turn_dt and next_turn_dt > now:
                    # No more overdue turns
                    break

                # Process next overdue turn
                result = await process_single_turn(session, force=False)
                if result is None:
                    # CAS update returned 0 rows or paused
                    break

                await session.commit()
                processed_count += 1
                await self._dispatch_turn_outputs(session, result)

        logger.info("Overdue turns catch-up complete", processed_turns=processed_count)
        return processed_count

    async def force_turn(self) -> Optional[TurnResult]:
        """Forces immediate execution of a turn."""
        async with self.session_factory() as session:
            result = await process_single_turn(session, force=True)
            if result:
                await session.commit()
                await self._dispatch_turn_outputs(session, result)
                self._wake_event.set()
                return result
            return None

    async def _run_loop(self) -> None:
        """Main in-memory timer loop."""
        # 1. Catch up overdue turns first on startup
        try:
            await self.catch_up_overdue_turns()
        except Exception as e:
            logger.error("Error during initial turn catch-up", error=str(e))

        while self._running:
            try:
                # Read next turn timestamp into memory once
                async with self.session_factory() as session:
                    state = await get_or_create_global_state(session)
                    next_turn_at = state.next_turn_at
                    is_paused = state.is_paused

                now = utc_now()

                if next_turn_at is not None and next_turn_at.tzinfo is None:
                    next_turn_at = next_turn_at.replace(tzinfo=timezone.utc)

                if is_paused or next_turn_at is None:
                    # Sleep until woken by force_turn or resume
                    self._wake_event.clear()
                    await self._wake_event.wait()
                    continue

                sleep_seconds = (next_turn_at - now).total_seconds()

                if sleep_seconds > 0:
                    # Sleep in memory until next turn is due (no DB polling)
                    self._wake_event.clear()
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=sleep_seconds)
                        # Woken prematurely by an event
                        continue
                    except asyncio.TimeoutError:
                        # Timer expired naturally; turn is now due
                        pass

                # Turn is due; catch up / process turn
                await self.catch_up_overdue_turns()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in turn scheduler loop", error=str(exc))
                # Short backoff before retrying loop on unexpected error
                await asyncio.sleep(5)

    async def _dispatch_turn_outputs(self, session: AsyncSession, result: TurnResult) -> None:
        """Posts map summary embed and backup snapshots to Discord channels if configured."""
        if not self.bot or not self.bot.is_ready():
            return

        try:
            state = await get_or_create_global_state(session)

            # 1. Post Map & Summary Embed
            if state.map_channel_id:
                get_ch = getattr(self.bot, "get_configured_channel", self.bot.get_channel)
                channel = get_ch(state.map_channel_id)
                if channel:
                    embed = discord.Embed.from_dict(result.summary_embed_dict)
                    files = []
                    if result.map_bytes:
                        file_obj = discord.File(io.BytesIO(result.map_bytes), filename="map.png")
                        embed.set_image(url="attachment://map.png")
                        files.append(file_obj)

                    if hasattr(self.bot, "outbound_queue") and self.bot.outbound_queue:
                        await self.bot.outbound_queue.enqueue(channel, embed=embed, files=files)
                    else:
                        await channel.send(embed=embed, files=files)

            # 2. Post Backup Snapshot
            if state.backup_channel_id and result.snapshot_data:
                get_ch = getattr(self.bot, "get_configured_channel", self.bot.get_channel)
                backup_channel = get_ch(state.backup_channel_id)
                if backup_channel:
                    snapshot_json = json.dumps(result.snapshot_data, indent=2).encode("utf-8")
                    file_obj = discord.File(
                        io.BytesIO(snapshot_json),
                        filename=f"sylus_snapshot_turn_{result.turn_number}.json",
                    )
                    if hasattr(self.bot, "outbound_queue") and self.bot.outbound_queue:
                        await self.bot.outbound_queue.enqueue(
                            backup_channel,
                            content=f"📦 **Sylus Snapshot Backup** (Turn {result.turn_number})",
                            files=[file_obj],
                        )
                    else:
                        await backup_channel.send(
                            content=f"📦 **Sylus Snapshot Backup** (Turn {result.turn_number})",
                            file=file_obj,
                        )
        except Exception as err:
            logger.error("Failed to post turn outputs to Discord channels", error=str(err))
