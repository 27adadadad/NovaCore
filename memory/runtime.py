from __future__ import annotations

import asyncio
from typing import Any

from novacore.conversation import ConversationManager
from novacore.memory.extractor import extract_and_store
from novacore.memory.store import MemoryStore


class AutoMemoryRunner:
    """管理不阻塞主 Agent 回答的自动记忆后台任务。"""

    def __init__(
        self,
        *,
        enabled: bool,
        max_candidates: int,
        client: Any,
        conversation: ConversationManager,
        store: MemoryStore,
    ) -> None:
        self.enabled = enabled
        self.max_candidates = max_candidates
        self.client = client
        self.conversation = conversation
        self.store = store
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending_count(self) -> int:
        return len(self._tasks)

    def schedule(self) -> None:
        if not self.enabled:
            return

        task = asyncio.create_task(self._extract())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _extract(self) -> None:
        try:
            await extract_and_store(
                self.client,
                self.conversation,
                self.store,
                max_candidates=self.max_candidates,
            )
        except Exception:
            # 自动记忆是附加能力，不能影响主任务或 CLI 的退出流程。
            return

    async def drain(self) -> None:
        tasks = tuple(self._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
