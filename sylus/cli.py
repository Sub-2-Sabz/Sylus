import asyncio
import argparse
import sys
from sylus.db.base import get_session
from sylus.engine.turn import process_single_turn
from sylus.logging import setup_logging, get_logger

logger = get_logger(__name__)


async def fast_forward_turns(turns_to_process: int) -> int:
    """Fast-forwards N turns sequentially."""
    completed = 0
    for _ in range(turns_to_process):
        async with get_session() as session:
            res = await process_single_turn(session, force=True)
            if res:
                await session.commit()
                completed += 1
                logger.info("Fast-forwarded turn", turn_number=res.turn_number)
            else:
                logger.warning("Turn processing skipped or aborted.")
                break
    return completed


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Sylus CLI tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ff_parser = subparsers.add_parser("fast-forward", help="Fast-forward N turns")
    ff_parser.add_argument("turns", type=int, nargs="?", default=1, help="Number of turns to fast-forward")
    ff_parser.add_argument("--turns", type=int, dest="turns_opt", help="Number of turns to fast-forward")

    args = parser.parse_args()

    if args.command == "fast-forward":
        num_turns = args.turns_opt if args.turns_opt is not None else args.turns
        completed = asyncio.run(fast_forward_turns(num_turns))
        print(f"Fast-forwarded {completed}/{num_turns} turns.")


if __name__ == "__main__":
    main()
