from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.database import engine

T = TypeVar("T")


def run_async_task(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Run async code safely inside a Celery fork worker.

    Celery tasks must not reuse the global async SQLAlchemy engine across
    multiple ``asyncio.run()`` calls — asyncpg connections bind to one loop.
    """

    async def _runner() -> T:
        await engine.dispose()
        try:
            return await coro_factory()
        finally:
            # Close pooled asyncpg connections while their loop is still alive.
            await engine.dispose()

    return asyncio.run(_runner())
