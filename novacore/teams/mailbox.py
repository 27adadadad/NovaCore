from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from novacore.teams.models import (
    MailboxMessage,
    MessageType,
)
from novacore.teams.store import (
    TEAM_DATA_VERSION,
    TeamStoreError,
    _atomic_write_json,
    _read_json,
    _resolve_team_dir,
    _resolve_teams_dir,
)


_MAILBOX_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9_-]{1,64}$"
)


class MailboxError(RuntimeError):
    """Mailbox 消息无法安全保存、读取或归档。"""


def _validate_mailbox_id(
    value: str,
    label: str,
) -> None:
    """校验会参与目录或文件名计算的 ID。"""

    if _MAILBOX_ID_PATTERN.fullmatch(value) is None:
        raise MailboxError(
            f"{label} must contain only letters, "
            "numbers, underscores, and hyphens "
            "and be 1-64 characters long"
        )


def _message_to_dict(
    message: MailboxMessage,
) -> dict[str, Any]:
    """把 MailboxMessage 转换为 JSON 字典。"""

    return {
        "version": TEAM_DATA_VERSION,
        "message_id": message.message_id,
        "sender_id": message.sender_id,
        "recipient_id": message.recipient_id,
        "message_type": message.message_type.value,
        "content": message.content,
        "task_id": message.task_id,
        "created_at": message.created_at.isoformat(),
    }


def _require_message_string(
    data: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    """读取消息中的必需字符串字段。"""

    value = data.get(key)

    if not isinstance(value, str):
        raise MailboxError(
            f"message.{key} must be a string"
        )

    if not allow_empty and not value:
        raise MailboxError(
            f"message.{key} cannot be empty"
        )

    return value


def _message_from_dict(
    value: Any,
) -> MailboxMessage:
    """把 JSON 对象恢复为 MailboxMessage。"""

    if not isinstance(value, dict):
        raise MailboxError(
            "message data must be an object"
        )

    version = value.get("version")

    if (
        type(version) is not int
        or version != TEAM_DATA_VERSION
    ):
        raise MailboxError(
            "unsupported message data version: "
            f"{version!r}"
        )

    raw_type = _require_message_string(
        value,
        "message_type",
    )

    try:
        message_type = MessageType(raw_type)
    except ValueError as exc:
        raise MailboxError(
            "message.message_type is invalid: "
            f"{raw_type}"
        ) from exc

    raw_task_id = value.get("task_id")

    if raw_task_id is not None:
        if (
            not isinstance(raw_task_id, str)
            or not raw_task_id
        ):
            raise MailboxError(
                "message.task_id must be a "
                "non-empty string or null"
            )

    raw_created_at = value.get("created_at")

    if not isinstance(raw_created_at, str):
        raise MailboxError(
            "message.created_at must be an "
            "ISO datetime string"
        )

    try:
        created_at = datetime.fromisoformat(
            raw_created_at
        )
    except ValueError as exc:
        raise MailboxError(
            "message.created_at is not a valid "
            "ISO datetime"
        ) from exc

    message_id = _require_message_string(
        value,
        "message_id",
    )
    sender_id = _require_message_string(
        value,
        "sender_id",
    )
    recipient_id = _require_message_string(
        value,
        "recipient_id",
    )

    for identifier, label in (
        (message_id, "message_id"),
        (sender_id, "sender_id"),
        (recipient_id, "recipient_id"),
    ):
        _validate_mailbox_id(
            identifier,
            label,
        )

    return MailboxMessage(
        message_id=message_id,
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_type=message_type,
        content=_require_message_string(
            value,
            "content",
            allow_empty=True,
        ),
        task_id=raw_task_id,
        created_at=created_at,
    )


class Mailbox:
    """持久化 Coordinator 与 Teammate 之间的消息。"""

    def __init__(
        self,
        work_dir: str | Path,
        team_id: str,
    ) -> None:
        try:
            teams_dir = _resolve_teams_dir(
                work_dir
            )
        except TeamStoreError as exc:
            raise MailboxError(str(exc)) from exc

        try:
            self._team_dir = _resolve_team_dir(
                teams_dir,
                team_id,
            )
        except TeamStoreError as exc:
            raise MailboxError(str(exc)) from exc

    def _recipient_dirs(
        self,
        recipient_id: str,
    ) -> tuple[Path, Path]:
        """安全计算接收者的 inbox 与 processed 目录。"""

        _validate_mailbox_id(
            recipient_id,
            "recipient_id",
        )

        raw_mailboxes_dir = (
            self._team_dir
            / "mailboxes"
        )
        raw_recipient_dir = (
            raw_mailboxes_dir
            / recipient_id
        )

        for path, label in (
            (raw_mailboxes_dir, "mailboxes directory"),
            (raw_recipient_dir, "recipient directory"),
        ):
            if path.is_symlink():
                raise MailboxError(
                    f"{label} cannot be a symlink"
                )

        mailboxes_dir = raw_mailboxes_dir.resolve()
        recipient_dir = raw_recipient_dir.resolve()

        try:
            mailboxes_dir.relative_to(
                self._team_dir
            )
            recipient_dir.relative_to(
                mailboxes_dir
            )
        except ValueError as exc:
            raise MailboxError(
                "mailbox path escaped the Team directory"
            ) from exc

        inbox_dir = recipient_dir / "inbox"
        processed_dir = recipient_dir / "processed"

        for path, label in (
            (inbox_dir, "inbox"),
            (processed_dir, "processed"),
        ):
            if path.is_symlink():
                raise MailboxError(
                    f"{label} cannot be a symlink"
                )

        return (
            inbox_dir.resolve(),
            processed_dir.resolve(),
        )

    def _message_path(
        self,
        directory: Path,
        message_id: str,
    ) -> Path:
        """安全计算一封消息在指定目录中的文件路径。"""

        _validate_mailbox_id(
            message_id,
            "message_id",
        )
        raw_path = (
            directory
            / f"{message_id}.json"
        )

        if raw_path.is_symlink():
            raise MailboxError(
                "message file cannot be a symlink"
            )

        path = raw_path.resolve()

        try:
            path.relative_to(directory)
        except ValueError as exc:
            raise MailboxError(
                "message path escaped its mailbox directory"
            ) from exc

        return path

    def _load_message(
        self,
        path: Path,
        recipient_id: str,
    ) -> MailboxMessage:
        """读取消息并校验文件名与接收者。"""

        if path.is_symlink():
            raise MailboxError(
                f"message file cannot be a symlink: {path}"
            )

        try:
            message = _message_from_dict(
                _read_json(path)
            )
        except TeamStoreError as exc:
            raise MailboxError(str(exc)) from exc

        if message.message_id != path.stem:
            raise MailboxError(
                "message ID does not match its filename: "
                f"{path.name}"
            )

        if message.recipient_id != recipient_id:
            raise MailboxError(
                "message recipient does not match its "
                "mailbox directory"
            )

        return message

    def send(
        self,
        message: MailboxMessage,
    ) -> None:
        """把一封新消息原子写入接收者 inbox。"""

        _validate_mailbox_id(
            message.sender_id,
            "sender_id",
        )
        inbox_dir, processed_dir = (
            self._recipient_dirs(
                message.recipient_id
            )
        )
        inbox_path = self._message_path(
            inbox_dir,
            message.message_id,
        )
        processed_path = self._message_path(
            processed_dir,
            message.message_id,
        )

        if (
            inbox_path.exists()
            or processed_path.exists()
        ):
            raise MailboxError(
                "message ID already exists: "
                f"{message.message_id}"
            )

        try:
            _atomic_write_json(
                inbox_path,
                _message_to_dict(message),
            )
        except TeamStoreError as exc:
            raise MailboxError(str(exc)) from exc

    def list_pending(
        self,
        recipient_id: str,
    ) -> tuple[MailboxMessage, ...]:
        """返回接收者尚未确认的全部消息。"""

        inbox_dir, _ = self._recipient_dirs(
            recipient_id
        )

        if not inbox_dir.exists():
            return ()

        try:
            paths = sorted(
                path
                for path in inbox_dir.iterdir()
                if path.suffix == ".json"
            )
        except OSError as exc:
            raise MailboxError(
                f"could not list inbox {inbox_dir}: {exc}"
            ) from exc

        messages = tuple(
            self._load_message(
                path,
                recipient_id,
            )
            for path in paths
        )

        return tuple(
            sorted(
                messages,
                key=lambda message: (
                    message.created_at,
                    message.message_id,
                ),
            )
        )

    def acknowledge(
        self,
        recipient_id: str,
        message_id: str,
    ) -> MailboxMessage:
        """把已处理消息从 inbox 原子移动到 processed。"""

        inbox_dir, processed_dir = (
            self._recipient_dirs(recipient_id)
        )
        inbox_path = self._message_path(
            inbox_dir,
            message_id,
        )
        processed_path = self._message_path(
            processed_dir,
            message_id,
        )

        if not inbox_path.is_file():
            raise MailboxError(
                "pending message does not exist: "
                f"{message_id}"
            )

        if processed_path.exists():
            raise MailboxError(
                "processed message already exists: "
                f"{message_id}"
            )

        message = self._load_message(
            inbox_path,
            recipient_id,
        )

        try:
            processed_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
            os.replace(
                inbox_path,
                processed_path,
            )
        except OSError as exc:
            raise MailboxError(
                "could not acknowledge message "
                f"{message_id}: {exc}"
            ) from exc

        return message
