from __future__ import annotations

from novacore.path_sandbox import PathSandbox


def test_teammate_sandbox_rejects_sibling_worktree_paths(tmp_path):
    worker_one = tmp_path / "worktrees" / "worker-one"
    worker_two = tmp_path / "worktrees" / "worker-two"
    worker_one.mkdir(parents=True)
    worker_two.mkdir(parents=True)

    allowed, reason = PathSandbox(worker_one).check(
        str(worker_two / "secret.py")
    )

    assert allowed is False
    assert "outside project root" in reason.lower()
