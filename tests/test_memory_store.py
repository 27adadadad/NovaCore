from __future__ import annotations

from novacore.memory.store import MemoryStore


def test_append_persists_project_memory_and_injects_it(tmp_path):
    store = MemoryStore(
        tmp_path / "project",
        user_memory_dir=tmp_path / "user-memory",
    )

    store.append("project", "Use pytest for all tests.")

    assert "Use pytest for all tests." in store.read("project")
    assert "Project memory" in store.build_system_prompt()

