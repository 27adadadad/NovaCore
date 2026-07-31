from __future__ import annotations

import time
import asyncio
import uuid

from typing import (
    TYPE_CHECKING,
    Literal,
)
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from novacore.agent import Agent
    from novacore.conversation import (
        ConversationManager,
    )

TaskStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
]


@dataclass
class BackgroundTask:
    task_id: str
    name: str
    agent_type: str
    prompt: str

    status: TaskStatus = "running"
    result: str = ""
    error: str = ""

    start_time: float = field(
        default_factory=time.monotonic,
    )
    end_time: float | None = None



    @property
    def duration_seconds(
        self,
    ) -> float:
        end_time = (
            self.end_time
            if self.end_time is not None
            else time.monotonic()
        )

        return (
            end_time
            - self.start_time
        )

class TaskManager:
    def __init__(
        self,
    ) -> None:
        self._tasks: dict[
            str,
            BackgroundTask,
        ] = {}

        self._async_tasks: dict[
            str,
            asyncio.Task[None],
        ] = {}

        self._completed_queue: (
            asyncio.Queue[str]
        ) = asyncio.Queue()

    def launch(
        self,
        agent: Agent,
        conversation: ConversationManager,
        prompt: str,
        name: str = "",
    ) -> str:
        task_id = uuid.uuid4().hex[:8]

        record = BackgroundTask(
            task_id=task_id,
            name=(
                name
                or agent.agent_type
            ),
            agent_type=agent.agent_type,
            prompt=prompt,
        )

        self._tasks[task_id] = record

        async_task = asyncio.create_task(
            self._run_background(
                task_id,
                agent,
                conversation,
            )
        )

        self._async_tasks[task_id] = (
            async_task
        )

        return task_id

    async def _run_background(
        self,
        task_id: str,
        agent: Agent,
        conversation: ConversationManager,
    ) -> None:
        record = self._tasks.get(
            task_id
        )

        if record is None:
            return

        try:
            result = await (
                agent.run_to_completion(
                    record.prompt,
                    conversation=conversation,
                )
            )

        except asyncio.CancelledError:
            record.status = "cancelled"
            record.error = (
                "Task was cancelled"
            )
            raise

        except Exception as exc:
            record.status = "failed"
            record.error = (
                f"{type(exc).__name__}: {exc}"
            )

        else:
            record.status = "completed"
            record.result = result

        finally:
            record.end_time = (
                time.monotonic()
            )

            self._async_tasks.pop(
                task_id,
                None,
            )

            self._completed_queue.put_nowait(
                task_id
            )

    def get(
        self,
        task_id: str,
    ) -> BackgroundTask | None:
        return self._tasks.get(
            task_id
        )

    def list_tasks(
        self,
    ) -> list[BackgroundTask]:
        return list(
            self._tasks.values()
        )

    def cancel(
        self,
        task_id: str,
    ) -> bool:
        record = self._tasks.get(
            task_id
        )

        if (
            record is None
            or record.status != "running"
        ):
            return False

        async_task = self._async_tasks.get(
            task_id
        )

        if (
            async_task is None
            or async_task.done()
        ):
            return False

        return async_task.cancel()


    def poll_completed(
        self,
    ) -> list[BackgroundTask]:
        completed: list[
            BackgroundTask
        ] = []

        while True:
            try:
                task_id = (
                    self._completed_queue
                    .get_nowait()
                )
            except asyncio.QueueEmpty:
                break

            record = self._tasks.get(
                task_id
            )

            if record is not None:
                completed.append(
                    record
                )

        return completed

    def has_running(
        self,
    ) -> bool:
        return any(
            record.status == "running"
            for record in self._tasks.values()
        )

    async def wait_all(
        self,
    ) -> None:
        while True:
            running_tasks = [
                async_task
                for async_task
                in self._async_tasks.values()
                if not async_task.done()
            ]

            if not running_tasks:
                return

            await asyncio.gather(
                *running_tasks,
                return_exceptions=True,
            )

    async def shutdown(
        self,
    ) -> None:
        running_tasks = [
            async_task
            for async_task
            in self._async_tasks.values()
            if not async_task.done()
        ]

        for async_task in running_tasks:
            async_task.cancel()

        if running_tasks:
            await asyncio.gather(
                *running_tasks,
                return_exceptions=True,
            )