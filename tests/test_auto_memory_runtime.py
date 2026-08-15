from __future__ import annotations

import asyncio

from novacore.conversation import ConversationManager
from novacore.memory.runtime import AutoMemoryRunner
from novacore.memory.store import MemoryStore


async def test_runner_schedules_extraction_without_blocking_caller(
    monkeypatch,
    tmp_path,
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_extract(*_args, **_kwargs):
        started.set()
        await release.wait()
        return ()

    monkeypatch.setattr(
        "novacore.memory.runtime.extract_and_store",
        delayed_extract,
    )
    runner = AutoMemoryRunner(
        enabled=True,
        max_candidates=3,
        client=object(),
        conversation=ConversationManager(),
        store=MemoryStore(tmp_path / "project", tmp_path / "user"),
    )

    runner.schedule()
    await started.wait()

    assert runner.pending_count == 1
    release.set()
    await runner.drain()
    assert runner.pending_count == 0
