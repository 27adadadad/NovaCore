from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from novacore.worktree import Worktree


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(timezone.utc)


class TeamStatus(str, Enum):
    """团队本身的生命周期状态。"""

    ACTIVE = "active"
    CLOSED = "closed"


class TeammateStatus(str, Enum):
    """队友 Agent 当前所处的运行状态。"""

    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    STOPPED = "stopped"


class SharedTaskStatus(str, Enum):
    """共享任务从创建到结束可能经历的状态。"""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class MessageType(str, Enum):
    """Coordinator 与 Teammate 之间的消息类型。"""

    INSTRUCTION = "instruction"
    RESULT = "result"
    STATUS = "status"
    TEXT = "text"


@dataclass(frozen=True)
class Team:
    """记录一个可持久化的 Agent 团队。"""

    team_id: str
    name: str
    lead_agent_id: str
    status: TeamStatus = TeamStatus.ACTIVE
    member_ids: tuple[str, ...] = ()
    created_at: datetime = field(
        default_factory=_utc_now,
    )


@dataclass(frozen=True)
class Teammate:
    """记录一个队友的身份、会话和隔离工作区。"""

    teammate_id: str
    name: str
    agent_type: str
    session_id: str
    worktree: Worktree
    status: TeammateStatus = TeammateStatus.IDLE
    current_task_id: str | None = None
    error: str = ""
    created_at: datetime = field(
        default_factory=_utc_now,
    )


@dataclass(frozen=True)
class SharedTask:
    """记录由 Coordinator 分配给队友的业务任务。"""

    task_id: str
    title: str
    description: str = ""
    status: SharedTaskStatus = (
        SharedTaskStatus.PENDING
    )
    assignee_id: str | None = None
    result: str = ""
    error: str = ""
    created_at: datetime = field(
        default_factory=_utc_now,
    )
    updated_at: datetime = field(
        default_factory=_utc_now,
    )


@dataclass(frozen=True)
class MailboxMessage:
    """记录一封等待投递或已经归档的团队消息。"""

    message_id: str
    sender_id: str
    recipient_id: str
    message_type: MessageType
    content: str
    task_id: str | None = None
    created_at: datetime = field(
        default_factory=_utc_now,
    )
