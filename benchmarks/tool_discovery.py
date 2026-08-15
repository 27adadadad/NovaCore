from __future__ import annotations

import json
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
