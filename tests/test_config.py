from __future__ import annotations

from novacore.config import load_auto_memory_settings


def test_auto_memory_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("AUTO_MEMORY_ENABLED", "true")
    monkeypatch.setenv("AUTO_MEMORY_MAX_CANDIDATES", "2")

    settings = load_auto_memory_settings()

    assert settings.enabled is True
    assert settings.max_candidates == 2

