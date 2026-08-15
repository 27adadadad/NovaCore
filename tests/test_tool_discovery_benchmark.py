from __future__ import annotations

from benchmarks.tool_discovery import compare_tool_payloads


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
