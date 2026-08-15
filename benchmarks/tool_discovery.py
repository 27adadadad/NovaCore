from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _payload_size(tools: list[dict[str, Any]]) -> int:
    return len(
        json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def compare_tool_payloads(
    tools: list[dict[str, Any]],
    discovered_names: set[str],
) -> dict[str, int | float]:
    """比较全量 schema 与按需发现后的 schema 载荷大小。"""

    discovered = [
        tool
        for tool in tools
        if tool.get("function", {}).get("name") in discovered_names
    ]
    all_payload_bytes = _payload_size(tools)
    discovered_payload_bytes = _payload_size(discovered)
    savings_ratio = (
        0.0
        if all_payload_bytes == 0
        else 1 - discovered_payload_bytes / all_payload_bytes
    )
    return {
        "tool_count": len(tools),
        "discovered_tool_count": len(discovered),
        "all_payload_bytes": all_payload_bytes,
        "discovered_payload_bytes": discovered_payload_bytes,
        "all_payload_approx_tokens": round(all_payload_bytes / 4),
        "discovered_payload_approx_tokens": round(discovered_payload_bytes / 4),
        "savings_ratio": round(savings_ratio, 4),
    }


def run_fixture(
    fixture_path: str | Path,
    output_path: str | Path,
) -> dict[str, int | float]:
    """读取固定 fixture 并写出稳定的 JSON 基准报告。"""

    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    tools = fixture["tools"]
    discovered_names = set(fixture["discovered_names"])
    result = compare_tool_payloads(tools, discovered_names)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
