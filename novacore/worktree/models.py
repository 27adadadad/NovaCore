from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    """记录一个由 NovaCore 创建的 Git Worktree。"""

    name: str
    path: Path
    branch: str
    based_on: str
    initial_head: str
    created_at: datetime = field(
        default_factory=datetime.now,
    )


@dataclass(frozen=True)
class WorktreeChanges:
    """记录 Worktree 相对创建时提交产生的变化。"""

    uncommitted: int = 0
    new_commits: int = 0
    reliable: bool = True
    reason: str = ""

    @property
    def should_preserve(self) -> bool:
        """无法确认安全或存在变化时必须保留。"""

        return (
            not self.reliable
            or self.uncommitted > 0
            or self.new_commits > 0
        )


@dataclass(frozen=True)
class CleanupResult:
    """描述 Worktree 目录与临时分支各自的清理结果。"""

    worktree: Worktree
    changes: WorktreeChanges
    worktree_removed: bool
    branch_removed: bool
    reason: str
