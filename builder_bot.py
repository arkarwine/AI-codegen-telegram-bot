"""Ubuntu/systemd entrypoint for the Builder Bot service."""

from __future__ import annotations

import asyncio

from builder.bot import run_builder_bot


if __name__ == "__main__":
    asyncio.run(run_builder_bot())
