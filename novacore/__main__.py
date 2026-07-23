from __future__ import annotations
from pathlib import Path

import argparse
import asyncio
import sys

from novacore.client import DashScopeClient
from novacore.config import load_config
from novacore.tools import create_default_registry
from novacore.agent import (
    Agent,
    StreamText,
    ToolResultEvent,
    ToolUseEvent,
    LoopComplete,
    TurnComplete,
    ErrorEvent,
    PermissionRequest,
    PermissionResponse,
)
from novacore.permissions import (
    PermissionChecker,
    PermissionMode,
)
from novacore.path_sandbox import PathSandbox
from novacore.command_safety import DangerousCommandDetector


from novacore.tui import run_tui

def parse_args()->argparse.Namespace:
    parser = argparse.ArgumentParser(
    description="Minimal terminal AI coding assistant"
)

    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream the response"
    )
    
    parser.add_argument(
        "-p", 
        "--prompt",
        default=None,
        help="task to send to the agent",
    )

    parser.add_argument(
        "--permission-mode",
        choices=[mode.value for mode in PermissionMode],
        default=PermissionMode.DEFAULT.value,
        help="Permission mode used for tool execution",
    )
    
    args = parser.parse_args()

    if args.prompt is None and args.stream:
        parser.error(
            "--stream requires --prompt"
        )

    return args

async def main()->None:
    args = parse_args()

    sandbox = PathSandbox(project_root=Path.cwd())
    config = load_config()
    client = DashScopeClient(config)
    registry = create_default_registry(
        work_dir=sandbox.project_root
    )
    detector = DangerousCommandDetector()
    permission_checker = PermissionChecker(
        detector=detector,
        sandbox=sandbox,
        mode = PermissionMode(args.permission_mode),
    )
    agent = Agent(
        client=client,
        registry=registry,
        permission_checker=permission_checker,
    ) 

    if args.prompt is None:
        await run_tui(agent)
        return       

    if args.stream:
        async for event in agent.stream_to_completion(
            args.prompt
        ):
            if isinstance(event, StreamText):
                print(
                    event.text,
                    end="",
                    flush=True,
                )

            elif isinstance(event, ToolUseEvent):
                print(
                    f"\n[tool] calling {event.tool_name}",
                    file=sys.stderr,
                    flush=True,
                )

            elif isinstance(event, PermissionRequest):
                print(
                    (
                        f"\n[permission] {event.description}\n"
                        f"Reason: {event.reason}\n"
                        "Allow? [y/N]: "
                    ),
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

                answer = await asyncio.to_thread(
                    sys.stdin.readline
                )
                answer = answer.strip().lower()

                response = (
                    PermissionResponse.ALLOW
                    if answer in {"y", "yes"}
                    else PermissionResponse.DENY
                )

                if not event.future.done():
                    event.future.set_result(response)
                

            elif isinstance(event, ToolResultEvent):
                status = "failed" if event.is_error else "completed"

                print(
                    f"[tool] {event.tool_name} {status}",
                    file=sys.stderr,
                    flush=True,
                )

            elif isinstance(event, TurnComplete):
                print(
                    f"[turn] {event.turn} completed",
                    file=sys.stderr,
                    flush=True,
                )

            elif isinstance(event, LoopComplete):
                print(
                    f"\n[done] {event.total_turns} turn(s)",
                    file=sys.stderr,
                    flush=True,
                )

            elif isinstance(event, ErrorEvent):
                print(
                    f"\n[error] {event.message}",
                    file=sys.stderr,
                    flush=True,
                )
        print()

    else:
         answer = await agent.run_to_completion(
              args.prompt
         )
         print(answer)
                

if __name__ == "__main__":
        asyncio.run(main())
