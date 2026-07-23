# NovaCore

NovaCore is a terminal AI coding assistant built as a from-scratch learning implementation. It supports an OpenAI-compatible model client, multi-turn conversations, streaming responses, tool calls, permission checks, path boundaries, and a Textual interface.

## Current Capabilities

- OpenAI-compatible DashScope client
- Conversation history and message serialization
- Streaming Agent loop with tool-result feedback
- ReadFile, WriteFile, and Bash tools
- Permission modes, dangerous-command detection, and project path checks
- CLI and Textual TUI modes
- Interactive Allow/Deny permission requests in the TUI

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

## Project Status

The core Agent, tool, permission, and minimal TUI paths are implemented. Context compression, persistent memory, MCP, skills, subagents, teams, and worktree support remain on the roadmap. See `PROGRESS.md` for the learning timeline and current scope.
