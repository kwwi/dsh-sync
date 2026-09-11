"""报告生成进度事件."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ProgressCallback = Callable[[str, str, str], Awaitable[None]]

STEPS = ("bazi", "analysis", "fate", "names", "finalize")


async def emit_progress(
    on_progress: ProgressCallback | None,
    step: str,
    title: str,
    summary: str,
) -> None:
    import logging
    _log = logging.getLogger("uvicorn")
    _log.info("进度 [%s] %s：%s", step, title, summary)
    if on_progress:
        await on_progress(step, title, summary)
