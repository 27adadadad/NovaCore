# README Verification Update Design

## Goal

Make the repository README accurately describe the verified capabilities in the
agent-resume-alignment branch without changing NovaCore source code or project
layout.

## Changes

1. Add an Automatic Memory section after the existing Memory section. It will
   document the default-disabled flag, the two environment variables, background
   extraction, candidate limits, validation, sensitive-data filtering, and
   idempotent upsert behavior.
2. Add a Deferred Tool Benchmark section after Deferred Tools. It will state
   the reproducible 100-tool fixture result: 32,701 bytes reduced to 982 bytes
   when three tools are activated, about 97% lower. The token figure will be
   labelled an estimate based on UTF-8 bytes divided by four.
3. Add a Documentation section linking the architecture, security, demo,
   verification report, and resume-verified project description.
4. Replace the obsolete claim that automated tests are skipped with commands
   for the pytest suite and benchmark, plus the covered behavior areas.

## Boundaries And Verification

Only `README.md` changes. The commands documented in the README must succeed:

```powershell
python -m pytest tests -q
python -m benchmarks.tool_discovery --fixture benchmarks/fixtures/tools_100.json --output benchmarks/results/tool_discovery.json
```
