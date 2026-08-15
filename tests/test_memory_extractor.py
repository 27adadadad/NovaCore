from __future__ import annotations

import json

from novacore.memory.extractor import parse_candidates


def test_parse_candidates_keeps_stable_project_constraint():
    payload = json.dumps(
        [
            {
                "scope": "project",
                "category": "constraint",
                "title": "test-framework",
                "content": "Use pytest for all automated tests.",
            }
        ]
    )

    candidates = parse_candidates(payload)

    assert len(candidates) == 1
    assert candidates[0].title == "test-framework"
    assert candidates[0].scope == "project"


def test_parse_candidates_drops_sensitive_content():
    payload = json.dumps(
        [
            {
                "scope": "user",
                "category": "preference",
                "title": "api-key",
                "content": "DASHSCOPE_API_KEY=secret-value",
            }
        ]
    )

    assert parse_candidates(payload) == []


def test_parse_candidates_rejects_malformed_or_unknown_fields():
    assert parse_candidates("not json") == []
    assert parse_candidates(
        '[{"scope":"project","category":"constraint",'
        '"title":"style","content":"Use black.","extra":"no"}]'
    ) == []

