from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _load_novacore_for_flat_checkout() -> None:
    """让 benchmark CLI 复用旧版 flat checkout 的包导入方式。"""

    try:
        import novacore  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    import importlib.util
    import sys

    package_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "novacore",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load NovaCore package from the checkout")
    module = importlib.util.module_from_spec(spec)
    sys.modules["novacore"] = module
    spec.loader.exec_module(module)


_load_novacore_for_flat_checkout()

from novacore.tool_search import ToolSearch
from novacore.tools import ToolRegistry, ToolResult


def _payload_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def compare_tool_payloads(tools: list[dict[str, Any]], discovered_names: set[str]) -> dict[str, int | float]:
    """比较全量 schema 与按需发现后的 schema 载荷大小。"""
    discovered = [tool for tool in tools if tool.get("function", {}).get("name") in discovered_names]
    all_payload_bytes = _payload_size(tools)
    discovered_payload_bytes = _payload_size(discovered)
    savings_ratio = 0.0 if all_payload_bytes == 0 else 1 - discovered_payload_bytes / all_payload_bytes
    return {
        "tool_count": len(tools),
        "discovered_tool_count": len(discovered),
        "all_payload_bytes": all_payload_bytes,
        "discovered_payload_bytes": discovered_payload_bytes,
        "all_payload_approx_tokens": round(all_payload_bytes / 4),
        "discovered_payload_approx_tokens": round(discovered_payload_bytes / 4),
        "savings_ratio": round(savings_ratio, 4),
    }


class _FixtureParams(BaseModel):
    """Fixture tool 参数；评测只需要发现 schema，不执行 fixture 工具。"""


class _FixtureTool:
    category = "read"

    def __init__(self, schema: dict[str, Any]) -> None:
        function = schema["function"]
        self.name = function["name"]
        self.description = function.get("description", "")
        self.schema = schema
        self.params_model = _FixtureParams

    def get_schema(self) -> dict[str, Any]:
        return self.schema

    async def execute(self, _params: _FixtureParams) -> ToolResult:
        return ToolResult(output="fixture tool execution is not part of this benchmark")


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fixture_tools(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    tools = fixture.get("tools")
    if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
        raise ValueError("fixture.tools must be a list of tool schemas")
    return tools


def _catalog(tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "name": tool.get("function", {}).get("name", ""),
            "description": tool.get("function", {}).get("description", ""),
        }
        for tool in tools
    ]


def _make_search(tools: list[dict[str, Any]], *, use_synonyms: bool) -> tuple[ToolRegistry, ToolSearch]:
    registry = ToolRegistry()
    search = ToolSearch(registry, use_synonyms=use_synonyms)
    registry.register(search)
    for schema in tools:
        registry.register(_FixtureTool(schema), deferred=True)
    return registry, search


async def _evaluate_strategy(tools: list[dict[str, Any]], queries: list[dict[str, Any]], *, use_synonyms: bool) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    target_hit_count = 0
    target_miss_count = 0
    false_activation_count = 0
    correct_no_match_count = 0
    incorrect_no_match_count = 0

    for query_case in queries:
        registry, search = _make_search(tools, use_synonyms=use_synonyms)
        query = str(query_case["query"])
        expected = set(query_case.get("expected_names", []))
        params = search.params_model(query=query, max_results=int(query_case.get("max_results", 5)))
        tool_result = await search.execute(params)
        all_names = {tool.get("function", {}).get("name") for tool in tools}
        discovered = sorted(name for name in all_names - set(registry.get_deferred_tool_names()) if name)
        discovered_set = set(discovered)
        false_activations = sorted(discovered_set - expected)
        target_hit = expected.issubset(discovered_set) if expected else False
        no_match_handled = not expected and not discovered_set and tool_result.output.startswith("No deferred tools matched")

        if expected and target_hit:
            target_hit_count += 1
        elif expected:
            target_miss_count += 1
        if false_activations:
            false_activation_count += 1
        if not expected and no_match_handled:
            correct_no_match_count += 1
        elif not expected:
            incorrect_no_match_count += 1

        results.append({
            "id": query_case["id"],
            "category": query_case.get("category", "unspecified"),
            "query": query,
            "expected_names": sorted(expected),
            "discovered_names": discovered,
            "target_hit": target_hit,
            "false_activated_names": false_activations,
            "no_match_handled": no_match_handled,
            "tool_search_output": tool_result.output,
        })

    failures = [
        result
        for result in results
        if ((result["expected_names"] and not result["target_hit"]) or result["false_activated_names"] or (not result["expected_names"] and not result["no_match_handled"]))
    ]
    return {
        "target_hit_count": target_hit_count,
        "target_miss_count": target_miss_count,
        "false_activation_count": false_activation_count,
        "correct_no_match_count": correct_no_match_count,
        "incorrect_no_match_count": incorrect_no_match_count,
        "failure_count": len(failures),
        "results": results,
        "failure_cases": failures,
    }


def run_evaluation(fixture_path: str | Path, queries_path: str | Path) -> dict[str, Any]:
    """用真实 ToolSearch 对标注查询进行离线评测。"""
    fixture = _load_json(fixture_path)
    queries = _load_json(queries_path)
    tools = _fixture_tools(fixture)
    if not isinstance(queries, list):
        raise ValueError("queries file must contain a list")

    baseline = asyncio.run(_evaluate_strategy(tools, queries, use_synonyms=False))
    improved = asyncio.run(_evaluate_strategy(tools, queries, use_synonyms=True))
    catalog = _catalog(tools)
    _, search = _make_search(tools, use_synonyms=True)
    tool_search_schema = search.get_schema()
    payload_queries: list[dict[str, Any]] = []
    for query_case, result in zip(queries, improved["results"], strict=True):
        discovered_schemas = [tool for tool in tools if tool.get("function", {}).get("name") in result["discovered_names"]]
        deferred_payload = {"tool_catalog": catalog, "tools": [tool_search_schema, *discovered_schemas]}
        payload_queries.append({
            "id": query_case["id"],
            "discovered_schema_bytes": _payload_size(discovered_schemas),
            "deferred_request_bytes": _payload_size(deferred_payload),
            "message_bytes_included": False,
        })

    full_schema_bytes = _payload_size(tools)
    deferred_request_sizes = [
        item["deferred_request_bytes"]
        for item in payload_queries
    ]
    discovered_schema_sizes = [
        item["discovered_schema_bytes"]
        for item in payload_queries
    ]
    return {
        "query_count": len(queries),
        "baseline": baseline,
        "improved": improved,
        "payload": {
            "full_schema_bytes": full_schema_bytes,
            "full_request_bytes": _payload_size({"tools": tools}),
            "full_schema_approx_tokens": round(full_schema_bytes / 4),
            "catalog_bytes": _payload_size(catalog),
            "tool_search_schema_bytes": _payload_size([tool_search_schema]),
            "queries": payload_queries,
            "deferred_request_bytes_min": min(deferred_request_sizes),
            "deferred_request_bytes_max": max(deferred_request_sizes),
            "deferred_request_bytes_avg": round(
                sum(deferred_request_sizes) / len(deferred_request_sizes),
                2,
            ),
            "discovered_schema_bytes_min": min(discovered_schema_sizes),
            "discovered_schema_bytes_max": max(discovered_schema_sizes),
            "discovered_schema_bytes_avg": round(
                sum(discovered_schema_sizes) / len(discovered_schema_sizes),
                2,
            ),
            "message_bytes_included": False,
            "boundary": "full request has all fixture schemas; deferred request has catalog, ToolSearch, and schemas actually activated by ToolSearch; messages are excluded",
        },
    }


def _write_json(output_path: str | Path, result: dict[str, Any]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_fixture(fixture_path: str | Path, output_path: str | Path) -> dict[str, int | float]:
    """读取旧版固定 fixture 并写出兼容的 schema 字节报告。"""
    fixture = _load_json(fixture_path)
    tools = _fixture_tools(fixture)
    result = compare_tool_payloads(tools, set(fixture["discovered_names"]))
    _write_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline deferred-tool schema or ToolSearch benchmark.")
    parser.add_argument("--fixture", required=True, help="JSON tool fixture")
    parser.add_argument("--queries", help="JSON annotated ToolSearch queries")
    parser.add_argument("--output", required=True, help="JSON result path")
    args = parser.parse_args(argv)
    result = run_evaluation(args.fixture, args.queries) if args.queries else run_fixture(args.fixture, args.output)
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
