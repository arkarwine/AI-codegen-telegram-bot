"""Ubuntu/systemd entrypoint for the Runtime Engine service."""

from __future__ import annotations

import asyncio

from runtime.engine import run_runtime_engine


if __name__ == "__main__":
    asyncio.run(run_runtime_engine())
