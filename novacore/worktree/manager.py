from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from novacore.worktree.changes import (
    inspect_worktree_changes,
    run_git_command,
)
from novacore.worktree.models import (
    CleanupResult,
    Worktree,
    WorktreeChanges,
)
from novacore.worktree.slug import (
    flatten_slug,
    validate_slug,
)


_OBJECT_ID_PATTERN = re.compile(
    r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$"
)


@dataclass(frozen=True)
class _GitWorktreeRecord:
    """记录 git worktree list 返回的一条结构化结果。"""

    path: Path
    head: str
    branch: str | None
    locked: bool = False
    prunable: bool = False


def _parse_git_worktree_list(
    output: str,
) -> tuple[_GitWorktreeRecord, ...]:
    """解析 git worktree list --porcelain 输出。"""

    records: list[_GitWorktreeRecord] = []
    current_path: Path | None = None
    current_head = ""
    current_branch: str | None = None
    current_locked = False
    current_prunable = False

    def finish_record() -> None:
        nonlocal current_path
        nonlocal current_head
        nonlocal current_branch
        nonlocal current_locked
        nonlocal current_prunable

        if current_path is None:
            return

        if not current_head:
            raise WorktreeError(
                "git worktree record is missing HEAD: "
                f"{current_path}"
            )

        records.append(
            _GitWorktreeRecord(
                path=current_path,
                head=current_head,
                branch=current_branch,
                locked=current_locked,
                prunable=current_prunable,
            )
        )
        current_path = None
        current_head = ""
        current_branch = None
        current_locked = False
        current_prunable = False

    for line in [*output.splitlines(), ""]:
        if not line:
            finish_record()
            continue

        if line.startswith("worktree "):
            if current_path is not None:
                raise WorktreeError(
                    "git worktree records are not "
                    "separated by a blank line"
                )

            raw_path = line.removeprefix(
                "worktree "
            )

            if not raw_path:
                raise WorktreeError(
                    "git worktree record has an "
                    "empty path"
                )

            current_path = Path(raw_path)
            continue

        if current_path is None:
            raise WorktreeError(
                "git worktree field appeared before "
                "its worktree path"
            )

        if line.startswith("HEAD "):
            current_head = line.removeprefix(
                "HEAD "
            )
        elif line.startswith("branch "):
            raw_branch = line.removeprefix(
                "branch "
            )
            prefix = "refs/heads/"
            current_branch = (
                raw_branch.removeprefix(prefix)
                if raw_branch.startswith(prefix)
                else raw_branch
            )
        elif line == "detached":
            current_branch = None
        elif (
            line == "locked"
            or line.startswith("locked ")
        ):
            current_locked = True
        elif (
            line == "prunable"
            or line.startswith("prunable ")
        ):
            current_prunable = True

    return tuple(records)


class WorktreeError(RuntimeError):
    """Worktree 生命周期操作无法安全完成。"""


class WorktreeManager:
    """集中管理当前进程创建的 Git Worktree。"""

    def __init__(
        self,
        repo_root: str | Path,
        worktree_dir: str | Path | None = None,
    ) -> None:
        self.repo_root = (
            Path(repo_root)
            .expanduser()
            .resolve()
        )

        if worktree_dir is None:
            resolved_worktree_dir = (
                self.repo_root
                / ".novacore"
                / "worktrees"
            ).resolve()
        else:
            candidate = (
                Path(worktree_dir)
                .expanduser()
            )

            if not candidate.is_absolute():
                candidate = (
                    self.repo_root
                    / candidate
                )

            resolved_worktree_dir = (
                candidate.resolve()
            )

        try:
            resolved_worktree_dir.relative_to(
                self.repo_root
            )
        except ValueError as exc:
            raise WorktreeError(
                "worktree directory must stay "
                "inside the repository root"
            ) from exc

        self.worktree_dir = (
            resolved_worktree_dir
        )

        # 创建和清理会修改同一份 Git 与内存状态，必须串行执行。
        self._lock = asyncio.Lock()
        self._active: dict[str, Worktree] = {}

    def _build_worktree_target(
        self,
        name: str,
    ) -> tuple[Path, str]:
        """把逻辑名称转换为目标目录和临时分支名。"""

        error = validate_slug(name)

        if error is not None:
            raise WorktreeError(error)

        flat_slug = flatten_slug(name)
        path = (
            self.worktree_dir
            / flat_slug
        ).resolve()
        branch = f"worktree-{flat_slug}"

        try:
            path.relative_to(
                self.worktree_dir
            )
        except ValueError as exc:
            raise WorktreeError(
                "worktree path escaped its "
                "configured directory"
            ) from exc

        return path, branch

    async def _ensure_target_available(
        self,
        name: str,
        path: Path,
        branch: str,
    ) -> None:
        """确认名称、目录和临时分支都没有被占用。"""

        if name in self._active:
            raise WorktreeError(
                "worktree is already active: "
                f"{name}"
            )

        if path.exists() or path.is_symlink():
            raise WorktreeError(
                "worktree path already exists: "
                f"{path}"
            )

        branches = await self._run_git(
            [
                "branch",
                "--list",
                "--format=%(refname:short)",
                branch,
            ]
        )

        if branches.stdout.strip():
            raise WorktreeError(
                "worktree branch already exists: "
                f"{branch}"
            )

    async def _run_git(
        self,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        """运行 Git，并把失败统一转换为 WorktreeError。"""

        try:
            result = await run_git_command(
                args,
                cwd=self.repo_root,
            )
        except (
            subprocess.SubprocessError,
            OSError,
        ) as exc:
            raise WorktreeError(
                "git command failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
                or (
                    "exit code "
                    f"{result.returncode}"
                )
            )

            raise WorktreeError(
                f"git {args[0]} failed: {detail}"
            )

        return result

    async def _ensure_repository_root(
        self,
    ) -> None:
        """确认 repo_root 正好是当前 Git 仓库根目录。"""

        result = await self._run_git(
            [
                "rev-parse",
                "--show-toplevel",
            ]
        )

        raw_root = result.stdout.strip()

        if not raw_root:
            raise WorktreeError(
                "git returned an empty "
                "repository root"
            )

        actual_root = (
            Path(raw_root)
            .expanduser()
            .resolve()
        )

        if actual_root != self.repo_root:
            raise WorktreeError(
                "repo_root must be the Git "
                "repository root: "
                f"{actual_root}"
            )

    async def _ensure_repository_clean(
        self,
    ) -> None:
        """确认主仓库没有需要提交的本地修改。"""

        result = await self._run_git(
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
            ]
        )

        if result.stdout.strip():
            raise WorktreeError(
                "repository must be clean before "
                "creating a worktree"
            )

    async def _get_current_head(
        self,
    ) -> str:
        """取得主仓库当前提交的完整哈希。"""

        result = await self._run_git(
            [
                "rev-parse",
                "HEAD",
            ]
        )

        head = result.stdout.strip()

        if not head:
            raise WorktreeError(
                "git returned an empty HEAD"
            )

        return head

    async def _list_registered_worktrees(
        self,
    ) -> tuple[_GitWorktreeRecord, ...]:
        """取得 Git 当前登记的全部 Worktree。"""

        result = await self._run_git(
            [
                "worktree",
                "list",
                "--porcelain",
            ]
        )

        return _parse_git_worktree_list(
            result.stdout
        )

    async def adopt(
        self,
        worktree: Worktree,
    ) -> Worktree:
        """验证并接管一个已经存在的受管 Worktree。"""

        async with self._lock:
            expected_path, expected_branch = (
                self._build_worktree_target(
                    worktree.name
                )
            )

            try:
                saved_path = (
                    worktree.path
                    .expanduser()
                    .resolve()
                )
            except (
                OSError,
                RuntimeError,
            ) as exc:
                raise WorktreeError(
                    "could not resolve saved worktree "
                    f"path: {exc}"
                ) from exc

            if saved_path != expected_path:
                raise WorktreeError(
                    "saved worktree path does not match "
                    "the configured worktree directory: "
                    f"{saved_path}"
                )

            if worktree.branch != expected_branch:
                raise WorktreeError(
                    "saved worktree branch does not match "
                    "its generated branch: "
                    f"{worktree.branch}"
                )

            existing = self._active.get(
                worktree.name
            )

            if existing is not None:
                if existing == worktree:
                    return existing

                raise WorktreeError(
                    "a different worktree is already "
                    "active with this name: "
                    f"{worktree.name}"
                )

            await self._ensure_repository_root()
            records = (
                await self._list_registered_worktrees()
            )
            matches: list[_GitWorktreeRecord] = []

            for record in records:
                try:
                    record_path = (
                        record.path
                        .expanduser()
                        .resolve()
                    )
                except (
                    OSError,
                    RuntimeError,
                ) as exc:
                    raise WorktreeError(
                        "could not resolve Git worktree "
                        f"path {record.path}: {exc}"
                    ) from exc

                if record_path == expected_path:
                    matches.append(record)

            if not matches:
                raise WorktreeError(
                    "saved worktree is not registered "
                    f"with Git: {expected_path}"
                )

            if len(matches) != 1:
                raise WorktreeError(
                    "Git returned multiple records for "
                    f"worktree path: {expected_path}"
                )

            record = matches[0]

            if record.locked:
                raise WorktreeError(
                    "saved worktree is locked and cannot "
                    "be adopted safely"
                )

            if record.prunable:
                raise WorktreeError(
                    "saved worktree is marked prunable "
                    "and cannot be adopted safely"
                )

            if record.branch is None:
                raise WorktreeError(
                    "detached worktree cannot be adopted"
                )

            if record.branch != expected_branch:
                raise WorktreeError(
                    "Git worktree branch does not match "
                    "the saved branch: "
                    f"{record.branch}"
                )

            for object_id, label in (
                (
                    worktree.initial_head,
                    "saved initial_head",
                ),
                (
                    record.head,
                    "Git worktree HEAD",
                ),
            ):
                if (
                    not isinstance(object_id, str)
                    or _OBJECT_ID_PATTERN.fullmatch(
                        object_id
                    )
                    is None
                ):
                    raise WorktreeError(
                        f"{label} is not a full Git "
                        "object ID"
                    )

            merge_base = await self._run_git(
                [
                    "merge-base",
                    worktree.initial_head,
                    record.head,
                ]
            )

            if (
                merge_base.stdout.strip().lower()
                != worktree.initial_head.lower()
            ):
                raise WorktreeError(
                    "saved initial_head is not an "
                    "ancestor of the current worktree "
                    "HEAD"
                )

            self._active[
                worktree.name
            ] = worktree

            return worktree

    async def create(
        self,
        name: str,
    ) -> Worktree:
        """从主仓库当前提交创建一个隔离 Worktree。"""

        # 创建会同时修改 Git、磁盘和 _active，整个过程不能交错。
        async with self._lock:
            path, branch = (
                self._build_worktree_target(
                    name
                )
            )

            await self._ensure_repository_root()
            await self._ensure_repository_clean()
            await self._ensure_target_available(
                name,
                path,
                branch,
            )

            initial_head = (
                await self._get_current_head()
            )

            try:
                self.worktree_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )
            except OSError as exc:
                raise WorktreeError(
                    "could not create worktree "
                    f"directory: {exc}"
                ) from exc

            # -b 只创建新分支；若发生竞态冲突，Git 会拒绝覆盖。
            await self._run_git(
                [
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(path),
                    initial_head,
                ]
            )

            worktree = Worktree(
                name=name,
                path=path,
                branch=branch,
                based_on="HEAD",
                initial_head=initial_head,
            )
            self._active[name] = worktree

            return worktree

    async def _inspect_cleanup_target(
        self,
        name: str,
    ) -> tuple[Worktree, WorktreeChanges]:
        """取得受管 Worktree，并检查删除前的变化。"""

        worktree = self._active.get(name)

        if worktree is None:
            raise WorktreeError(
                "worktree is not active: "
                f"{name}"
            )

        changes = await inspect_worktree_changes(
            worktree.path,
            worktree.initial_head,
        )

        return worktree, changes

    async def cleanup(
        self,
        name: str,
    ) -> CleanupResult:
        """仅在确认无变化时删除 Worktree 和临时分支。"""

        async with self._lock:
            worktree, changes = (
                await self._inspect_cleanup_target(
                    name
                )
            )

            if changes.should_preserve:
                if not changes.reliable:
                    detail = (
                        changes.reason
                        or "unknown inspection error"
                    )
                    reason = (
                        "worktree preserved because "
                        "change inspection was "
                        f"unreliable: {detail}"
                    )
                else:
                    reason = (
                        "worktree preserved: "
                        f"{changes.uncommitted} "
                        "uncommitted item(s), "
                        f"{changes.new_commits} "
                        "new commit(s)"
                    )

                return CleanupResult(
                    worktree=worktree,
                    changes=changes,
                    worktree_removed=False,
                    branch_removed=False,
                    reason=reason,
                )

            try:
                # 不使用 --force，让 Git 在竞态修改出现时再次拒绝删除。
                await self._run_git(
                    [
                        "worktree",
                        "remove",
                        str(worktree.path),
                    ]
                )
            except WorktreeError as exc:
                return CleanupResult(
                    worktree=worktree,
                    changes=changes,
                    worktree_removed=False,
                    branch_removed=False,
                    reason=(
                        "could not remove worktree: "
                        f"{exc}"
                    ),
                )

            self._active.pop(name, None)

            try:
                # -d 只删除已合并分支，不使用会强制删除的 -D。
                await self._run_git(
                    [
                        "branch",
                        "-d",
                        worktree.branch,
                    ]
                )
            except WorktreeError as exc:
                return CleanupResult(
                    worktree=worktree,
                    changes=changes,
                    worktree_removed=True,
                    branch_removed=False,
                    reason=(
                        "worktree removed, but branch "
                        f"was preserved: {exc}"
                    ),
                )

            return CleanupResult(
                worktree=worktree,
                changes=changes,
                worktree_removed=True,
                branch_removed=True,
                reason=(
                    "worktree and temporary branch "
                    "removed"
                ),
            )
