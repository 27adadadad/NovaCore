from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from novacore.teams.models import (
    SharedTask,
    SharedTaskStatus,
    Team,
    TeamStatus,
    Teammate,
    TeammateStatus,
)
from novacore.worktree import Worktree


TEAM_DATA_VERSION = 1
TEAMS_DIR = (
    Path(".novacore")
    / "teams"
)
_TEAM_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9_-]{1,64}$"
)


class TeamStoreError(ValueError):
    """Teams 持久化数据无法安全转换。"""


@dataclass(frozen=True)
class TeamSnapshot:
    """把一个 Team 和它的 Teammate 组成一次完整快照。"""

    team: Team
    teammates: tuple[Teammate, ...]


def _validate_team_id(
    team_id: str,
) -> None:
    """拒绝可能逃出 Teams 目录的 ID。"""

    if _TEAM_ID_PATTERN.fullmatch(team_id) is None:
        raise TeamStoreError(
            "team_id must contain only letters, "
            "numbers, underscores, and hyphens "
            "and be 1-64 characters long"
        )


def _resolve_teams_dir(
    work_dir: str | Path,
) -> Path:
    """安全计算项目内的 Teams 数据根目录。"""

    project_root = (
        Path(work_dir)
        .expanduser()
        .resolve()
    )
    teams_dir = (
        project_root
        / TEAMS_DIR
    ).resolve()

    try:
        teams_dir.relative_to(project_root)
    except ValueError as exc:
        raise TeamStoreError(
            "teams directory must stay inside "
            "the project root"
        ) from exc

    return teams_dir


def _resolve_team_dir(
    teams_dir: Path,
    team_id: str,
) -> Path:
    """把 Team ID 安全解析为团队目录。"""

    _validate_team_id(team_id)
    team_dir = (
        teams_dir
        / team_id
    ).resolve()

    try:
        team_dir.relative_to(teams_dir)
    except ValueError as exc:
        raise TeamStoreError(
            "team directory escaped the configured "
            "teams directory"
        ) from exc

    return team_dir


def _atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """先完整写入同目录临时文件，再原子替换正式文件。"""

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        raise TeamStoreError(
            f"could not create data directory: {exc}"
        ) from exc

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                payload,
                temp_file,
                ensure_ascii=False,
                indent=2,
            )
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, path)
    except (
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

        raise TeamStoreError(
            f"could not write JSON data {path}: {exc}"
        ) from exc


def _read_json(
    path: Path,
) -> Any:
    """读取 JSON，并把磁盘和语法错误统一包装。"""

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as data_file:
            return json.load(data_file)
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise TeamStoreError(
            f"could not load JSON data {path}: {exc}"
        ) from exc


def _validate_team_snapshot(
    snapshot: TeamSnapshot,
) -> None:
    """确认 Team 声明的成员与实际快照一致。"""

    declared_ids = snapshot.team.member_ids
    actual_ids = tuple(
        teammate.teammate_id
        for teammate in snapshot.teammates
    )

    if len(set(declared_ids)) != len(declared_ids):
        raise TeamStoreError(
            "team.member_ids cannot contain duplicates"
        )

    if len(set(actual_ids)) != len(actual_ids):
        raise TeamStoreError(
            "teammate IDs cannot contain duplicates"
        )

    if set(declared_ids) != set(actual_ids):
        raise TeamStoreError(
            "team.member_ids must match the saved "
            "teammate IDs"
        )


def _validate_shared_tasks(
    tasks: tuple[SharedTask, ...],
) -> None:
    """拒绝空或重复的 SharedTask ID。"""

    task_ids = tuple(
        task.task_id
        for task in tasks
    )

    if any(not task_id for task_id in task_ids):
        raise TeamStoreError(
            "task IDs cannot be empty"
        )

    if len(set(task_ids)) != len(task_ids):
        raise TeamStoreError(
            "task IDs cannot contain duplicates"
        )


def _require_dict(
    value: Any,
    label: str,
) -> dict[str, Any]:
    """要求 JSON 值是对象。"""

    if not isinstance(value, dict):
        raise TeamStoreError(
            f"{label} must be an object"
        )

    return value


def _require_list(
    value: Any,
    label: str,
) -> list[Any]:
    """要求 JSON 值是数组。"""

    if not isinstance(value, list):
        raise TeamStoreError(
            f"{label} must be an array"
        )

    return value


def _require_string(
    data: dict[str, Any],
    key: str,
    label: str,
    *,
    allow_empty: bool = False,
) -> str:
    """读取一个必需的字符串字段。"""

    value = data.get(key)

    if not isinstance(value, str):
        raise TeamStoreError(
            f"{label}.{key} must be a string"
        )

    if not allow_empty and not value:
        raise TeamStoreError(
            f"{label}.{key} cannot be empty"
        )

    return value


def _require_optional_string(
    data: dict[str, Any],
    key: str,
    label: str,
) -> str | None:
    """读取一个允许为 null 的字符串字段。"""

    value = data.get(key)

    if value is None:
        return None

    if not isinstance(value, str):
        raise TeamStoreError(
            f"{label}.{key} must be a string or null"
        )

    if not value:
        raise TeamStoreError(
            f"{label}.{key} cannot be empty"
        )

    return value


def _parse_datetime(
    value: Any,
    label: str,
) -> datetime:
    """把 ISO 时间字符串恢复为 datetime。"""

    if not isinstance(value, str):
        raise TeamStoreError(
            f"{label} must be an ISO datetime string"
        )

    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise TeamStoreError(
            f"{label} is not a valid ISO datetime"
        ) from exc


def _team_to_dict(
    team: Team,
) -> dict[str, Any]:
    """把 Team 转换为 JSON 可序列化字典。"""

    return {
        "team_id": team.team_id,
        "name": team.name,
        "lead_agent_id": team.lead_agent_id,
        "status": team.status.value,
        "member_ids": list(team.member_ids),
        "created_at": team.created_at.isoformat(),
    }


def _team_from_dict(
    value: Any,
) -> Team:
    """把 JSON 对象恢复为 Team。"""

    data = _require_dict(value, "team")
    raw_status = _require_string(
        data,
        "status",
        "team",
    )

    try:
        status = TeamStatus(raw_status)
    except ValueError as exc:
        raise TeamStoreError(
            f"team.status is invalid: {raw_status}"
        ) from exc

    raw_member_ids = _require_list(
        data.get("member_ids"),
        "team.member_ids",
    )
    member_ids: list[str] = []

    for index, member_id in enumerate(
        raw_member_ids
    ):
        if (
            not isinstance(member_id, str)
            or not member_id
        ):
            raise TeamStoreError(
                "team.member_ids"
                f"[{index}] must be a non-empty string"
            )

        member_ids.append(member_id)

    if len(set(member_ids)) != len(member_ids):
        raise TeamStoreError(
            "team.member_ids cannot contain duplicates"
        )

    return Team(
        team_id=_require_string(
            data,
            "team_id",
            "team",
        ),
        name=_require_string(
            data,
            "name",
            "team",
        ),
        lead_agent_id=_require_string(
            data,
            "lead_agent_id",
            "team",
        ),
        status=status,
        member_ids=tuple(member_ids),
        created_at=_parse_datetime(
            data.get("created_at"),
            "team.created_at",
        ),
    )


def _worktree_to_dict(
    worktree: Worktree,
) -> dict[str, Any]:
    """把 Worktree 转换为 JSON 可序列化字典。"""

    return {
        "name": worktree.name,
        "path": str(worktree.path),
        "branch": worktree.branch,
        "based_on": worktree.based_on,
        "initial_head": worktree.initial_head,
        "created_at": worktree.created_at.isoformat(),
    }


def _worktree_from_dict(
    value: Any,
) -> Worktree:
    """把 JSON 对象恢复为 Worktree 记录。"""

    data = _require_dict(value, "teammate.worktree")

    # 这里只恢复记录；路径是否安全由 WorktreeManager.adopt() 检查。
    return Worktree(
        name=_require_string(
            data,
            "name",
            "teammate.worktree",
        ),
        path=Path(
            _require_string(
                data,
                "path",
                "teammate.worktree",
            )
        ),
        branch=_require_string(
            data,
            "branch",
            "teammate.worktree",
        ),
        based_on=_require_string(
            data,
            "based_on",
            "teammate.worktree",
        ),
        initial_head=_require_string(
            data,
            "initial_head",
            "teammate.worktree",
        ),
        created_at=_parse_datetime(
            data.get("created_at"),
            "teammate.worktree.created_at",
        ),
    )


def _teammate_to_dict(
    teammate: Teammate,
) -> dict[str, Any]:
    """把 Teammate 转换为 JSON 可序列化字典。"""

    return {
        "teammate_id": teammate.teammate_id,
        "name": teammate.name,
        "agent_type": teammate.agent_type,
        "session_id": teammate.session_id,
        "worktree": _worktree_to_dict(
            teammate.worktree
        ),
        "status": teammate.status.value,
        "current_task_id": teammate.current_task_id,
        "error": teammate.error,
        "created_at": teammate.created_at.isoformat(),
    }


def _teammate_from_dict(
    value: Any,
    index: int,
) -> Teammate:
    """把 JSON 对象恢复为 Teammate。"""

    label = f"teammates[{index}]"
    data = _require_dict(value, label)
    raw_status = _require_string(
        data,
        "status",
        label,
    )

    try:
        status = TeammateStatus(raw_status)
    except ValueError as exc:
        raise TeamStoreError(
            f"{label}.status is invalid: {raw_status}"
        ) from exc

    return Teammate(
        teammate_id=_require_string(
            data,
            "teammate_id",
            label,
        ),
        name=_require_string(
            data,
            "name",
            label,
        ),
        agent_type=_require_string(
            data,
            "agent_type",
            label,
        ),
        session_id=_require_string(
            data,
            "session_id",
            label,
        ),
        worktree=_worktree_from_dict(
            data.get("worktree")
        ),
        status=status,
        current_task_id=(
            _require_optional_string(
                data,
                "current_task_id",
                label,
            )
        ),
        error=_require_string(
            data,
            "error",
            label,
            allow_empty=True,
        ),
        created_at=_parse_datetime(
            data.get("created_at"),
            f"{label}.created_at",
        ),
    )


def _shared_task_to_dict(
    task: SharedTask,
) -> dict[str, Any]:
    """把 SharedTask 转换为 JSON 可序列化字典。"""

    return {
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "assignee_id": task.assignee_id,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _shared_task_from_dict(
    value: Any,
    index: int,
) -> SharedTask:
    """把 JSON 对象恢复为 SharedTask。"""

    label = f"tasks[{index}]"
    data = _require_dict(value, label)
    raw_status = _require_string(
        data,
        "status",
        label,
    )

    try:
        status = SharedTaskStatus(raw_status)
    except ValueError as exc:
        raise TeamStoreError(
            f"{label}.status is invalid: {raw_status}"
        ) from exc

    return SharedTask(
        task_id=_require_string(
            data,
            "task_id",
            label,
        ),
        title=_require_string(
            data,
            "title",
            label,
        ),
        description=_require_string(
            data,
            "description",
            label,
            allow_empty=True,
        ),
        status=status,
        assignee_id=_require_optional_string(
            data,
            "assignee_id",
            label,
        ),
        result=_require_string(
            data,
            "result",
            label,
            allow_empty=True,
        ),
        error=_require_string(
            data,
            "error",
            label,
            allow_empty=True,
        ),
        created_at=_parse_datetime(
            data.get("created_at"),
            f"{label}.created_at",
        ),
        updated_at=_parse_datetime(
            data.get("updated_at"),
            f"{label}.updated_at",
        ),
    )


def _team_snapshot_to_dict(
    snapshot: TeamSnapshot,
) -> dict[str, Any]:
    """把完整团队快照转换为 team.json 数据。"""

    return {
        "version": TEAM_DATA_VERSION,
        "team": _team_to_dict(snapshot.team),
        "teammates": [
            _teammate_to_dict(teammate)
            for teammate in snapshot.teammates
        ],
    }


def _team_snapshot_from_dict(
    value: Any,
) -> TeamSnapshot:
    """把 team.json 数据恢复为完整团队快照。"""

    data = _require_dict(value, "team data")
    version = data.get("version")

    if (
        type(version) is not int
        or version != TEAM_DATA_VERSION
    ):
        raise TeamStoreError(
            "unsupported team data version: "
            f"{version!r}"
        )

    raw_teammates = _require_list(
        data.get("teammates"),
        "teammates",
    )

    return TeamSnapshot(
        team=_team_from_dict(
            data.get("team")
        ),
        teammates=tuple(
            _teammate_from_dict(item, index)
            for index, item in enumerate(
                raw_teammates
            )
        ),
    )


def _shared_tasks_to_dict(
    tasks: tuple[SharedTask, ...],
) -> dict[str, Any]:
    """把共享任务集合转换为 tasks.json 数据。"""

    return {
        "version": TEAM_DATA_VERSION,
        "tasks": [
            _shared_task_to_dict(task)
            for task in tasks
        ],
    }


def _shared_tasks_from_dict(
    value: Any,
) -> tuple[SharedTask, ...]:
    """把 tasks.json 数据恢复为共享任务集合。"""

    data = _require_dict(value, "task data")
    version = data.get("version")

    if (
        type(version) is not int
        or version != TEAM_DATA_VERSION
    ):
        raise TeamStoreError(
            "unsupported task data version: "
            f"{version!r}"
        )

    raw_tasks = _require_list(
        data.get("tasks"),
        "tasks",
    )

    return tuple(
        _shared_task_from_dict(item, index)
        for index, item in enumerate(raw_tasks)
    )


class TeamStore:
    """保存和恢复 Team 与它的 Teammate。"""

    def __init__(
        self,
        work_dir: str | Path,
    ) -> None:
        self._teams_dir = _resolve_teams_dir(
            work_dir
        )

    def save(
        self,
        snapshot: TeamSnapshot,
    ) -> None:
        """把完整团队快照原子写入 team.json。"""

        _validate_team_snapshot(snapshot)
        team_dir = _resolve_team_dir(
            self._teams_dir,
            snapshot.team.team_id,
        )
        _atomic_write_json(
            team_dir / "team.json",
            _team_snapshot_to_dict(snapshot),
        )

    def load(
        self,
        team_id: str,
    ) -> TeamSnapshot | None:
        """按 ID 加载团队；文件不存在时返回 None。"""

        team_dir = _resolve_team_dir(
            self._teams_dir,
            team_id,
        )
        data_path = team_dir / "team.json"

        if not data_path.exists():
            return None

        snapshot = _team_snapshot_from_dict(
            _read_json(data_path)
        )

        if snapshot.team.team_id != team_id:
            raise TeamStoreError(
                "team.json team_id does not match "
                "its directory name"
            )

        _validate_team_snapshot(snapshot)
        return snapshot

    def list_team_ids(
        self,
    ) -> tuple[str, ...]:
        """列出磁盘中包含 team.json 的安全 Team ID。"""

        if not self._teams_dir.exists():
            return ()

        if not self._teams_dir.is_dir():
            raise TeamStoreError(
                "teams data path is not a directory: "
                f"{self._teams_dir}"
            )

        try:
            entries = sorted(
                self._teams_dir.iterdir(),
                key=lambda path: path.name,
            )
        except OSError as exc:
            raise TeamStoreError(
                "could not list teams directory: "
                f"{exc}"
            ) from exc

        team_ids: list[str] = []

        for entry in entries:
            if entry.is_symlink():
                raise TeamStoreError(
                    "team directory cannot be a "
                    f"symlink: {entry}"
                )

            if not entry.is_dir():
                continue

            _validate_team_id(entry.name)

            if (entry / "team.json").is_file():
                team_ids.append(entry.name)

        return tuple(team_ids)


class SharedTaskStore:
    """保存和恢复单个 Team 的 SharedTask。"""

    def __init__(
        self,
        work_dir: str | Path,
        team_id: str,
    ) -> None:
        teams_dir = _resolve_teams_dir(
            work_dir
        )
        self._team_dir = _resolve_team_dir(
            teams_dir,
            team_id,
        )

    def save(
        self,
        tasks: tuple[SharedTask, ...],
    ) -> None:
        """把任务集合原子写入 tasks.json。"""

        _validate_shared_tasks(tasks)
        _atomic_write_json(
            self._team_dir / "tasks.json",
            _shared_tasks_to_dict(tasks),
        )

    def load(
        self,
    ) -> tuple[SharedTask, ...]:
        """加载任务集合；文件不存在时返回空元组。"""

        data_path = self._team_dir / "tasks.json"

        if not data_path.exists():
            return ()

        tasks = _shared_tasks_from_dict(
            _read_json(data_path)
        )
        _validate_shared_tasks(tasks)
        return tasks
