from __future__ import annotations

import copy

from novacore.conversation import (
    ConversationManager,
    Message,
    ToolResultBlock,
)

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = f"""\
{FORK_BOILERPLATE_TAG}
This conversation was created by forking another agent.
Complete only the assigned task.
Do not create another conversation fork.
</fork_boilerplate>
"""


class ForkError(RuntimeError):
    pass


def build_fork_prompt(
    task: str,
) -> str:
    normalized_task = task.strip()

    if not normalized_task:
        raise ForkError(
            "Fork task cannot be empty"
        )

    return (
        f"{FORK_BOILERPLATE}\n"
        f"Task:\n{normalized_task}"
    )

def _find_pending_tool_use_ids(
    messages: list[Message],
) -> list[str]:
    pending: dict[str, None] = {}

    for message in messages:
        for tool_use in message.tool_uses:
            pending[
                tool_use.tool_use_id
            ] = None

        for tool_result in message.tool_results:
            pending.pop(
                tool_result.tool_use_id,
                None,
            )

    return list(pending)

def build_forked_conversation(
    parent: ConversationManager,
) -> ConversationManager:
    parent_messages = parent.get_messages()

    if any(
        FORK_BOILERPLATE_TAG
        in message.content
        for message in parent_messages
    ):
        raise ForkError(
            "Cannot fork a forked conversation"
        )

    copied_history = copy.deepcopy(
        parent_messages
    )

    forked = ConversationManager(
        history=copied_history
    )

    pending_ids = (
        _find_pending_tool_use_ids(
            copied_history
        )
    )

    if pending_ids:
        placeholders = [
            ToolResultBlock(
                tool_use_id=tool_use_id,
                content=(
                    "Tool execution interrupted "
                    "by conversation fork"
                ),
                is_error=True,
            )
            for tool_use_id in pending_ids
        ]

        forked.add_tool_results_message(
            placeholders
        )

    return forked