from __future__ import annotations

import json

from benchmarks.tool_discovery import (
    compare_tool_payloads,
    run_evaluation,
    run_fixture,
)


def test_compare_payloads_reports_smaller_discovered_subset():
    tools = [
        {
            "type": "function",
            "function": {
                "name": f"tool_{index}",
                "description": "A documented tool with a nested schema.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
        for index in range(10)
    ]

    result = compare_tool_payloads(tools, discovered_names={"tool_0", "tool_1"})

    assert result["tool_count"] == 10
    assert result["discovered_tool_count"] == 2
    assert result["discovered_payload_bytes"] < result["all_payload_bytes"]
    assert result["savings_ratio"] > 0


def test_run_fixture_writes_reproducible_json_report(tmp_path):
    fixture = tmp_path / "tools.json"
    output = tmp_path / "result.json"
    fixture.write_text(
        json.dumps(
            {
                "tools": [
                    {"type": "function", "function": {"name": "alpha"}},
                    {"type": "function", "function": {"name": "beta"}},
                ],
                "discovered_names": ["alpha"],
            }
        ),
        encoding="utf-8",
    )

    result = run_fixture(fixture, output)

    assert result["tool_count"] == 2
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_evaluation_calls_real_toolsearch_and_reports_payload_boundaries(tmp_path):
    fixture = tmp_path / "tools.json"
    queries = tmp_path / "queries.json"
    fixture.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "SearchDocs",
                            "description": "Search technical documentation",
                            "parameters": {"type": "object"},
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "WriteFile",
                            "description": "Write a file to disk",
                            "parameters": {"type": "object"},
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    queries.write_text(
        json.dumps(
            [
                {
                    "id": "synonym",
                    "category": "synonym",
                    "query": "find manuals",
                    "expected_names": ["SearchDocs"],
                },
                {
                    "id": "no-match",
                    "category": "no_match",
                    "query": "play music",
                    "expected_names": [],
                },
            ]
        ),
        encoding="utf-8",
    )

    result = run_evaluation(fixture, queries)

    assert result["query_count"] == 2
    assert result["baseline"]["target_miss_count"] >= 1
    assert result["improved"]["target_hit_count"] >= 1
    assert result["improved"]["correct_no_match_count"] == 1
    assert result["payload"]["tool_search_schema_bytes"] > 0
    assert result["payload"]["queries"][0]["deferred_request_bytes"] > 0
    assert result["payload"]["deferred_request_bytes_avg"] > 0
    assert result["payload"]["queries"][0]["message_bytes_included"] is False
