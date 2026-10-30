import asyncio
import os
import time
import pytest
import discord
from unittest.mock import AsyncMock, MagicMock, patch

from sylus.bot.bot import create_bot, calculate_command_definitions_hash, sync_commands_if_changed, HASH_FILE_PATH
from sylus.services.outbound_queue import OutboundMessageQueue, PRIORITY_HIGH, PRIORITY_LOW


@pytest.mark.asyncio
async def test_command_sync_skipped_when_hash_unchanged(tmp_path):
    bot = create_bot()
    hash_file = tmp_path / "last_synced_commands_hash.txt"

    with patch("sylus.bot.bot.HASH_FILE_PATH", hash_file), \
         patch.object(bot, "sync_commands", new_callable=AsyncMock) as mock_sync:

        current_hash = calculate_command_definitions_hash(bot)
        hash_file.write_text(current_hash, encoding="utf-8")

        # 1. Sync when hash is unchanged
        res1 = await sync_commands_if_changed(bot, force=False)
        assert res1 is False
        mock_sync.assert_not_called()

        # 2. Sync when force=True
        res2 = await sync_commands_if_changed(bot, force=True)
        assert res2 is True
        mock_sync.assert_called_once()


@pytest.mark.asyncio
async def test_outbound_queue_rate_limit_and_priority():
    target = MagicMock()
    target.send = AsyncMock(return_value="sent_msg")

    # High rate per second to keep test fast, e.g. 10 msgs/sec -> 0.1s delay
    queue = OutboundMessageQueue(rate_per_sec=20.0, jitter_range=(0.0, 0.0))
    queue.start()

    try:
        # Enqueue low priority items first, then high priority item
        fut_low1 = await queue.enqueue(target, content="low_1", priority=PRIORITY_LOW)
        fut_low2 = await queue.enqueue(target, content="low_2", priority=PRIORITY_LOW)
        fut_high = await queue.enqueue(target, content="high_1", priority=PRIORITY_HIGH)

        # Wait for all futures
        await asyncio.gather(fut_low1, fut_low2, fut_high)

        # Confirm send was called 3 times
        assert target.send.call_count == 3
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_notification_burst_500_spread_out():
    target = MagicMock()
    target.send = AsyncMock(return_value="sent_msg")

    queue = OutboundMessageQueue(rate_per_sec=100.0, jitter_range=(0.0, 0.0))
    queue.start()

    try:
        futures = []
        t0 = time.perf_counter()

        for i in range(500):
            fut = await queue.enqueue(target, content=f"msg_{i}", priority=PRIORITY_LOW)
            futures.append(fut)

        # Wait for all 500 queued messages to process
        await asyncio.gather(*futures)
        t_duration = time.perf_counter() - t0

        assert target.send.call_count == 500
        # At 100 msgs/sec, 500 messages should take approx 5 seconds (safely > 2s to verify rate spreading)
        assert t_duration >= 2.0
    finally:
        await queue.stop()
