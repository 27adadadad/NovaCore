# NovaCore

NovaCore is a terminal AI coding assistant built as a from-scratch learning implementation. It supports an OpenAI-compatible model client, multi-turn conversations, streaming responses, tool calls, persistent sessions, isolated subagents, and a Textual interface.

## Current Capabilities

- OpenAI-compatible DashScope client
- Conversation history and message serialization
- Streaming Agent loop with tool-result feedback
- ReadFile, WriteFile, Glob, Grep, and Bash tools
- Permission modes, dangerous-command detection, and project path checks
- CLI and Textual TUI modes
- Interactive Allow/Deny permission requests in CLI streaming and TUI modes
- Context compaction and JSONL Session resume
- Persistent project and user Memory
- Project and user Skills with on-demand loading
- Built-in, user, and project Agent definitions
- Foreground, background, forked, and Worktree-isolated subagents
- MCP stdio servers with deferred tool discovery
- In-process Teams with persistent tasks, Mailbox, independent Sessions, and Worktrees
- Hooks and parent/child Agent traces
- ToolSearch for loading deferred MCP and Teams tools only when needed

## Requirements

- Python 3.11 or newer
- A DashScope API key

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DASHSCOPE_API_KEY = "<your-api-key>"
```

Never commit or share a real API key.

## Run

Start the Textual interface:

```powershell
python -m novacore
```

Run a single prompt:

```powershell
python -m novacore -p "Summarize novacore/agent.py"
```

Use streaming CLI output:

```powershell
python -m novacore -p "Summarize novacore/agent.py" --stream
```

Resume a Session:

```powershell
python -m novacore --resume <session-id>
```

Local commands are available in the TUI and through `-p`:

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

## Local Definitions

Agent and Skill definitions use this precedence order:

```text
project > user > built-in
```

Project definitions are read from `.novacore/agents/*.md` and `.novacore/skills/*/SKILL.md`. User definitions use the same layout under `~/.novacore/`. Project Memory is stored in `.novacore/memory/MEMORY.md`; user Memory is stored in `~/.novacore/memory/MEMORY.md`.

Project runtime data, Sessions, Memory, Teams, Mailbox files, and Worktrees live under `.novacore/` and must not be committed.

MCP tools and Teams management tools are deferred. The model first calls `ToolSearch`, after which matching full schemas become available on the next model turn.

## Project Status

The single-process core is feature complete for the current learning scope. Platform-specific teammate backends such as tmux and iTerm2, concurrent execution of multiple tool calls within one model turn, and full compatibility with the reference project are intentionally out of scope.
