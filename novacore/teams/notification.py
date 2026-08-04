from __future__ import annotations

from typing import TYPE_CHECKING

from novacore.conversation import ConversationManager
from novacore.teams.models import MailboxMessage
from novacore.teams.models import TeamStatus

if TYPE_CHECKING:
    from novacore.teams.coordinator import Coordinator


MAX_TEAM_NOTIFICATION_CHARS = 5_000


def format_team_notification(
    message: MailboxMessage,
) -> str:
    """把持久 Mailbox 消息转换为父 Agent 可识别的上下文。"""

    content = message.content

    if len(content) > MAX_TEAM_NOTIFICATION_CHARS:
        content = (
            content[:MAX_TEAM_NOTIFICATION_CHARS]
            + "\n... (truncated)"
        )

    return (
        "<team-notification>\n"
        f"Message ID: {message.message_id}\n"
        f"From: {message.sender_id}\n"
        f"Task ID: {message.task_id or '(none)'}\n"
        f"Type: {message.message_type.value}\n"
        f"Content:\n{content}\n"
        "</team-notification>"
    )


def inject_team_notifications(
    conversation: ConversationManager,
    messages: tuple[MailboxMessage, ...],
) -> None:
    """把一组 Team 通知依次追加到父 Conversation。"""

    for message in messages:
        conversation.add_user_message(
            format_team_notification(message)
        )


async def collect_team_notifications(
    coordinator: Coordinator,
) -> tuple[MailboxMessage, ...]:
    """更新后台状态并取得 Coordinator 尚未确认的消息。"""

    team = coordinator.team

    if team is None:
        return ()

    if team.status == TeamStatus.ACTIVE:
        await coordinator.poll_completed()
        team = coordinator.team

        if team is None:
            return ()

    return coordinator.list_messages(
        team.lead_agent_id
    )


def acknowledge_team_notifications(
    coordinator: Coordinator,
    messages: tuple[MailboxMessage, ...],
) -> None:
    """在通知成功注入后逐封归档。"""

    for message in messages:
        coordinator.acknowledge_message(
            message.recipient_id,
            message.message_id,
        )
