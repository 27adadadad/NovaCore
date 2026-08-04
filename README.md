# NovaCore

NovaCore is a terminal AI coding assistant built from scratch as a learning-focused implementation. It combines an OpenAI-compatible model client, a multi-turn tool loop, persistent sessions, durable memory, isolated subagents, MCP tools, and an optional Textual interface.

The current scope is a single-process coding agent that can be understood and extended without relying on a large framework.

## Highlights

- OpenAI-compatible DashScope client with normal and streaming responses
- Multi-turn Agent loop with structured tool calls and tool-result feedback
- ReadFile, WriteFile, Glob, Grep, and Bash tools
- Permission modes, dangerous-command detection, and project path boundaries
- Textual TUI and non-interactive CLI modes
- Context compaction and JSONL Session persistence/resume
- Project-level and user-level durable Memory
- Built-in, user, and project Agent/Skill definitions with hot reload
- Foreground, background, forked, and Worktree-isolated subagents
- MCP stdio clients with paginated tool discovery
- In-process Teams with persistent tasks, Mailbox messages, Sessions, and Worktrees
- Hooks and parent/child Agent traces
- Deferred MCP and Teams schemas loaded on demand through ToolSearch

## Runtime Flow

```text
CLI or TUI prompt
    -> ConversationManager
    -> Agent loop
    -> model client
    -> text response, or one or more tool requests
    -> permission and path checks
    -> ToolRegistry / MCP / child Agent / Team
    -> tool results return to ConversationManager
    -> next model turn
    -> final response
```

`Session` stores conversation history. `Memory` stores durable facts and preferences across Sessions. Teams and background tasks return results to the parent Conversation as structured notifications.

## Requirements

- Python 3.11 or newer
- A DashScope API key
- Git when using Worktree-isolated subagents or Teams

## Setup

Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DASHSCOPE_API_KEY = "<your-api-key>"
```

The `.env.example` file documents the required variable, but NovaCore does not automatically load `.env` files. Set the variable in the current shell or through your own environment manager.

Never commit, log, or share a real API key.

## Run

Start the Textual interface:

```powershell
python -m novacore
```

Run one non-streaming prompt:

```powershell
python -m novacore -p "Summarize novacore/agent.py"
```

Stream one prompt:

```powershell
python -m novacore -p "Summarize novacore/agent.py" --stream
```

Resume a Session:

```powershell
python -m novacore --resume <session-id>
```

Select a permission mode:

```powershell
python -m novacore --permission-mode default
python -m novacore --permission-mode acceptEdits
python -m novacore --permission-mode bypassPermissions
```

`bypassPermissions` should only be used in a trusted environment. Worktree agents still enforce their isolated path boundary.

## Local Commands

Local slash commands are available in the TUI and through `-p`:

```text
/help
/status
/tasks
/cancel <background-task-id>
/compact
/memory [all|project|user]
/team
/team cancel <shared-task-id>
/team resume <teammate-id>
```

For example:

```powershell
python -m novacore -p "/status"
python -m novacore -p "/memory project"
```

## Deferred Tools

MCP tools and Teams management tools are registered as deferred tools. They do not appear in every model request. The model first calls `ToolSearch`; matching full schemas become available on the next model turn.

An exact discovery query looks like:

```text
select:TeamStatus,TeamTaskCreate
```

This keeps the default tool schema small while still allowing a Session to restore tools it has already used.

## MCP

Start NovaCore with the public example MCP configuration:

```powershell
python -m novacore --mcp-config novacore/examples/mcp.example.json
```

The example connects the local echo server in `novacore/examples/mcp_echo_server.py`. Local MCP configuration may contain commands, paths, environment variables, or credentials and should not be committed.

## Memory

NovaCore provides two fixed Memory scopes:

```text
Project: .novacore/memory/MEMORY.md
User:    ~/.novacore/memory/MEMORY.md
```

`RecallMemory` reads or searches Memory. `Remember` appends a durable entry and is treated as a write operation by the permission system. Startup injection and tool output are bounded so Memory cannot consume the entire model context.

Memory is separate from JSONL Sessions: resuming a Session restores conversation history, while Memory is loaded independently at startup.

## Agents And Skills

Definitions use this precedence order:

```text
project > user > built-in
```

Paths:

```text
Project Agent: .novacore/agents/*.md
User Agent:    ~/.novacore/agents/*.md
Project Skill: .novacore/skills/*/SKILL.md
User Skill:    ~/.novacore/skills/*/SKILL.md
```

Examples are available in `novacore/examples/agents/` and `novacore/examples/skills/`. Adding, modifying, renaming, or removing a definition updates the loader catalog without restarting NovaCore.

Child Agents cannot recursively call `Agent` or Teams management tools. Worktree teammates receive independent Conversations, Sessions, path-restricted tools, and Git Worktrees.

## Runtime Data And Security

Project runtime data lives under `.novacore/`, including Sessions, Memory, Teams, Mailboxes, and Worktrees. This directory must remain ignored by Git.

NovaCore applies several boundaries:

- Tool arguments are validated with Pydantic models.
- Write and command tools pass through the permission checker.
- File tools resolve paths against the active project or Worktree root.
- Worktree cleanup preserves directories with uncommitted changes, new commits, or unreliable Git state.
- Memory uses bounded UTF-8 files and atomic replacement.
- API keys and local MCP credentials are not stored in Session or Memory automatically.

## Project Status

The single-process core is complete for the current learning scope. Platform-specific teammate backends such as tmux and iTerm2, concurrent execution of multiple tool calls within one model turn, and full compatibility with the reference project are intentionally out of scope.

Automated tests are currently skipped by project choice. The implementation has been checked with AST/import validation, FakeClient flows, temporary Git repositories, Textual `run_test()`, CLI smoke checks, and earlier real-model Worktree/Teams runs.
