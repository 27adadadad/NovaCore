# README Verification Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `README.md` so its public claims and verification instructions match the merged agent-resume-alignment capabilities.

**Architecture:** This is a documentation-only update. Preserve existing installation, runtime, MCP, permissions, and Worktree content; insert factual capability sections beside their related sections and replace only the obsolete test-status paragraph.

**Tech Stack:** Markdown, Python 3.11, pytest, NovaCore benchmark module.

---

### Task 1: Update verified capability documentation

**Files:**
- Modify: `README.md`
- Reference: `docs/verification-report.md`
- Reference: `benchmarks/results/tool_discovery.json`

- [ ] **Step 1: Insert the automatic memory behavior after the existing Memory section**

Add a section that documents `AUTO_MEMORY_ENABLED`,
`AUTO_MEMORY_MAX_CANDIDATES`, default-disabled behavior, background execution,
validation, sensitive-data filtering, and idempotent `MEMORY.md` upsert.

- [ ] **Step 2: Insert the deferred-tool benchmark after Deferred Tools**

Document the 100-tool fixture, `32,701` versus `982` schema bytes, approximate
`97%` reduction, and that the token count is an UTF-8-byte divided-by-four
estimate rather than a provider billing measurement.

- [ ] **Step 3: Add the documentation index and current verification commands**

Link the architecture, security, demo, verification, and resume documents.
Replace the obsolete statement that tests are skipped with:

```powershell
python -m pytest tests -q
python -m benchmarks.tool_discovery --fixture benchmarks/fixtures/tools_100.json --output benchmarks/results/tool_discovery.json
```

- [ ] **Step 4: Verify the commands described by the README**

Run:

```powershell
python -m pytest tests -q
python -m benchmarks.tool_discovery --fixture benchmarks/fixtures/tools_100.json --output benchmarks/results/tool_discovery.json
```

Expected: pytest reports all tests passing; the benchmark recreates its JSON
result without errors.

- [ ] **Step 5: Commit and push the README update**

```powershell
git add README.md
git commit -m "docs: document verified agent capabilities"
git push
```
