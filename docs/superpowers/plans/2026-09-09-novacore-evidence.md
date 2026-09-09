# NovaCore Resume Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ToolSearch, streaming function calling, context compaction, and session recovery claims reproducible offline on the selected resume-alignment baseline.

**Architecture:** Keep the existing flat package and OpenAI-compatible client. Add a deterministic benchmark harness that invokes the real ToolSearch against a fixed deferred registry, and add focused Fake SDK/FakeClient tests around existing loop boundaries.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, Pydantic, OpenAI-compatible AsyncOpenAI, JSON/JSONL.

---

### Task 1: Restore dependency and command reproducibility

**Files:**
- Modify: `pyproject.toml`, `requirements-dev.txt`
- Modify: `README.md`

- [ ] Add `pytest` and `pytest-asyncio` to the dev installation path and remove the fixed `--basetemp=.pytest-tmp` option so `tmp_path` uses a writable system temp directory.
- [ ] Document `python -m pytest tests -q` and the benchmark CLI with fixture/query/output arguments; state that no API key or paid model is needed for verification.
- [ ] Run `python -m pytest tests -q` after installing dev dependencies and record the actual count.

### Task 2: Add failing streaming and loop regression tests

**Files:**
- Create: `tests/test_streaming_tool_calls.py`
- Modify: `tests/test_tool_search.py`, `tests/test_context.py`
- Create: `tests/test_session_recovery.py`

- [ ] Write tests first for interleaved indexed deltas, fragmented arguments, invalid/truncated JSON, and incomplete id/name.
- [ ] Add a FakeClient sequence test proving ToolSearch activation is visible only in the next model request.
- [ ] Add compaction and Session round-trip tests asserting tool-call/result id pairing and restored deferred activation.
- [ ] Run the focused tests and confirm new assertions fail for the missing behavior before implementation.

### Task 3: Implement minimal ToolSearch retrieval improvement

**Files:**
- Modify: `tools.py`, `tool_search.py`

- [ ] Preserve `ToolRegistry.search_deferred(query, limit)` compatibility while adding deterministic token normalization for case, separators, camel case, and simple plural forms.
- [ ] Add a small auditable synonym map for the fixture vocabulary; apply it only to lexical scoring and keep exact `select:Name` behavior unchanged.
- [ ] Keep ToolSearch as the only activation path and preserve next-turn schema exposure.
- [ ] Run the focused ToolSearch and Agent tests until green, then run the full suite.

### Task 4: Build real 20-query ToolSearch benchmark

**Files:**
- Modify: `benchmarks/fixtures/tools_100.json`
- Create: `benchmarks/fixtures/tool_search_queries.json`
- Modify: `benchmarks/tool_discovery.py`, `tests/test_tool_discovery_benchmark.py`
- Modify: `benchmarks/results/tool_discovery.json`

- [ ] Replace the invalid/synthetic fixture with valid JSON containing 100 varied schemas and deterministic catalog metadata.
- [ ] Add about 20 labeled queries across exact name, keyword, synonym, vague description, no match, and exact selection categories.
- [ ] Implement an argparse CLI that runs baseline and improved ToolSearch on fresh registries, records per-query results/failures, and reports full-schema versus catalog+ToolSearch+discovered-schema bytes.
- [ ] Add tests for JSON readability, deterministic output, real activation, no-match handling, and metric accounting.
- [ ] Run the CLI and validate the output with `python -m json.tool`.

### Task 5: Final documentation and evidence verification

**Files:**
- Modify: `docs/verification-report.md`, `docs/resume-verified.md`, `README.md`

- [ ] Replace historical 14/15-passed and 97%-only claims with the newly executed test count and benchmark result fields.
- [ ] Document current limitations: fixed offline lexical dataset, schema bytes versus approximate tokens, no cost/latency claim, and unchanged protocol/scope.
- [ ] Run the exact README commands, inspect `git diff` and `git status`, and ensure no secrets, generated temp directories, or unrelated branch changes are included.
