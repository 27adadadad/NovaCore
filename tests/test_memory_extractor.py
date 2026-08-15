from __future__ import annotations

import json

from novacore.client import ClientResponse
from novacore.conversation import ConversationManager
from novacore.memory.extractor import extract_and_store, parse_candidates
from novacore.memory.store import MemoryStore


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


class _ExtractionClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[list[dict], list[dict]]] = []

    async def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return ClientResponse(text=self.response)


async def test_extract_and_store_uses_no_tools_and_persists_candidates(tmp_path):
    conversation = ConversationManager()
    conversation.add_user_message("Use pytest for every test in this project.")
    conversation.add_assistant_message("I will use pytest.")
    client = _ExtractionClient(
        json.dumps(
            [
                {
                    "scope": "project",
                    "category": "constraint",
                    "title": "test-framework",
                    "content": "Use pytest for every automated test.",
                }
            ]
        )
    )
    store = MemoryStore(
        tmp_path / "project",
        user_memory_dir=tmp_path / "user-memory",
    )

    saved = await extract_and_store(client, conversation, store)

    assert [candidate.title for candidate in saved] == ["test-framework"]
    assert client.calls[0][1] == []
    assert store.list_entries("project")[0].content == (
        "Use pytest for every automated test."
    )
