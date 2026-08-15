from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from novacore.agents.task_manager import (
        BackgroundTask,
    )
    from novacore.conversation import (
        ConversationManager,
    )


MAX_NOTIFICATION_RESULT_LENGTH = 5000


def format_task_notification(
    task: BackgroundTask,
) -> str:
    if task.status == "completed":
        output = task.result
    else:
        output = task.error

    if not output:
        output = "(no output)"

    if len(output) > MAX_NOTIFICATION_RESULT_LENGTH:
        output = (
            output[:MAX_NOTIFICATION_RESULT_LENGTH]
            + "\n... (truncated)"
        )

    elapsed = f"{task.duration_seconds:.1f}s"

    return (
        "<task-notification>\n"
        f"Task ID: {task.task_id}\n"
        f"Agent: {task.name}\n"
        f"Status: {task.status}\n"
        f"Elapsed: {elapsed}\n"
        f"Result:\n{output}\n"
        "</task-notification>"
    )

def inject_task_notifications(
    conversation: ConversationManager,
    completed_tasks: list[BackgroundTask],
) -> None:
    for task in completed_tasks:
        notification = (
            format_task_notification(task)
        )

        conversation.add_user_message(
            notification
        )