"""Process launcher for the two independent services."""

from __future__ import annotations

import argparse
import asyncio

from builder.bot import run_builder_bot
from runtime.engine import run_runtime_engine


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Telegram AI Bot Builder")
    parser.add_argument("service", choices=("builder", "runtime"))
    args = parser.parse_args()

    if args.service == "builder":
        await run_builder_bot()
    else:
        await run_runtime_engine()


if __name__ == "__main__":
    asyncio.run(_main())
