from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from novacore.worktree.models import (
    WorktreeChanges,
)


GIT_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
}


async def run_git_command(
    args: list[str],
    cwd: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """在线程中运行非交互式 Git 命令。"""

    env = {
        **os.environ,
        **GIT_ENV_OVERRIDES,
    }

    # subprocess.run 会阻塞，放入工作线程可避免暂停 Agent 事件循环。
    return await asyncio.to_thread(
        subprocess.run,
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        env=env,
        check=False,
    )


async def inspect_worktree_changes(
    worktree_path: Path,
    initial_head: str,
) -> WorktreeChanges:
    """检查 Worktree 中未提交内容和新增提交。"""

    try:
        status = await run_git_command(
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--ignored=matching",
            ],
            cwd=worktree_path,
        )
    except (
        subprocess.SubprocessError,
        OSError,
    ) as exc:
        return WorktreeChanges(
            reliable=False,
            reason=(
                "git status failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    if status.returncode != 0:
        return WorktreeChanges(
            reliable=False,
            reason=(
                "git status failed: "
                f"{status.stderr.strip()}"
            ),
        )

    uncommitted = sum(
        1
        for line in status.stdout.splitlines()
        if line.strip()
    )

    try:
        commits = await run_git_command(
            [
                "rev-list",
                "--count",
                f"{initial_head}..HEAD",
            ],
            cwd=worktree_path,
        )
    except (
        subprocess.SubprocessError,
        OSError,
    ) as exc:
        return WorktreeChanges(
            uncommitted=uncommitted,
            reliable=False,
            reason=(
                "git rev-list failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    if commits.returncode != 0:
        return WorktreeChanges(
            uncommitted=uncommitted,
            reliable=False,
            reason=(
                "git rev-list failed: "
                f"{commits.stderr.strip()}"
            ),
        )

    try:
        new_commits = int(
            commits.stdout.strip()
        )
    except ValueError:
        return WorktreeChanges(
            uncommitted=uncommitted,
            reliable=False,
            reason=(
                "git rev-list returned an "
                "invalid commit count"
            ),
        )

    return WorktreeChanges(
        uncommitted=uncommitted,
        new_commits=new_commits,
    )
