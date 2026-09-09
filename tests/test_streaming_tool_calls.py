from __future__ import annotations

from types import SimpleNamespace

import pytest

from novacore.client import DashScopeClient, ToolCallComplete


def _delta(index, *, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for chunk in self.chunks:
            yield chunk


class _FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks

    async def create(self, **_kwargs):
        return _FakeStream(self.chunks)


def _client(chunks):
    client = DashScopeClient.__new__(DashScopeClient)
    client._model = "fake-model"
    client._sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=_FakeCompletions(chunks),
        )
    )
    return client


def _chunk(*deltas, content=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    tool_calls=list(deltas),
                )
            )
        ]
    )


@pytest.mark.asyncio
async def test_stream_reassembles_interleaved_calls_by_index():
    client = _client(
        [
            _chunk(
                _delta(0, call_id="call-a", name="SearchDocs", arguments='{"q":'),
                _delta(1, call_id="call-b", name="ReadFile", arguments='{"path":"'),
            ),
            _chunk(
                _delta(0, arguments='"api"}'),
                _delta(1, arguments='README.md"}'),
            ),
        ]
    )

    events = [event async for event in client.stream([], [])]

    assert all(isinstance(event, ToolCallComplete) for event in events)
    assert [(event.tool_call.tool_id, event.tool_call.tool_name) for event in events] == [
        ("call-a", "SearchDocs"),
        ("call-b", "ReadFile"),
    ]
    assert events[0].tool_call.arguments == {"q": "api"}
    assert events[1].tool_call.arguments == {"path": "README.md"}


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"q":', '{"q":]'])
async def test_stream_rejects_invalid_or_truncated_arguments(arguments):
    client = _client(
        [_chunk(_delta(0, call_id="call-a", name="SearchDocs", arguments=arguments))]
    )

    with pytest.raises(RuntimeError, match="Invalid arguments"):
        _ = [event async for event in client.stream([], [])]


@pytest.mark.asyncio
async def test_stream_rejects_call_without_id_or_name():
    client = _client([_chunk(_delta(0, arguments='{}'))])

    with pytest.raises(RuntimeError, match="Incomplete tool call"):
        _ = [event async for event in client.stream([], [])]
