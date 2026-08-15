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


def test_upsert_replaces_an_existing_titled_memory(tmp_path):
    store = MemoryStore(
        tmp_path / "project",
        user_memory_dir=tmp_path / "user-memory",
    )

    store.upsert("project", "test-framework", "Use pytest.")
    store.upsert("project", "test-framework", "Use pytest with fixtures.")

    entries = store.list_entries("project")
    assert len(entries) == 1
    assert entries[0].title == "test-framework"
    assert entries[0].content == "Use pytest with fixtures."

