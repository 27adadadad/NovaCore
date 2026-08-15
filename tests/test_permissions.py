from __future__ import annotations

from pydantic import BaseModel

from novacore.command_safety import DangerousCommandDetector
from novacore.path_sandbox import PathSandbox
from novacore.permissions import PermissionChecker, PermissionMode


class _Params(BaseModel):
    command: str


class _CommandTool:
    name = "Bash"
    description = "Run a command"
    category = "command"
    params_model = _Params


class _WriteTool:
    name = "WriteFile"
    description = "Write a file"
    category = "write"
    params_model = _Params


def test_dangerous_command_is_denied_even_in_bypass_mode(tmp_path):
    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(tmp_path),
        mode=PermissionMode.BYPASS,
    )

    decision = checker.check(_CommandTool(), {"command": "rm -rf /"})

    assert decision.effect == "deny"


def test_strict_sandbox_denies_write_outside_teammate_worktree(tmp_path):
    worktree = tmp_path / "worker"
    outside = tmp_path / "other-worker" / "note.py"
    worktree.mkdir()

    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(worktree),
        mode=PermissionMode.ACCEPT_EDITS,
        enforce_sandbox=True,
    )

    decision = checker.check(_WriteTool(), {"file_path": str(outside)})

    assert decision.effect == "deny"
    assert "strict path sandbox" in decision.reason.lower()

