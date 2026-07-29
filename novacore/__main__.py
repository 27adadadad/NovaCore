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
    CompactNotification,
)
from novacore.permissions import (
    PermissionChecker,
    PermissionMode,
)
from novacore.path_sandbox import PathSandbox
from novacore.command_safety import DangerousCommandDetector


from novacore.tui import run_tui
from novacore.conversation import ConversationManager
from novacore.session import SessionManager, make_compact_boundary
from novacore.context import CompactBoundary
from novacore.mcp import MCPManager, load_mcp_server_configs
from novacore.skills import (
    LoadSkill,
    SkillLoader,
)

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
        "--resume",
        default=None,
        metavar="SESSION_ID",
        help="Resume an existing session",
    )

    parser.add_argument(
        "--permission-mode",
        choices=[mode.value for mode in PermissionMode],
        default=PermissionMode.DEFAULT.value,
        help="Permission mode used for tool execution",
    )

    parser.add_argument(
        "--mcp-config",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Load MCP servers from "
            "a JSON configuration file"
        ),
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
    skill_loader = SkillLoader(
        sandbox.project_root
    )

    skill_loader.load_all()

    registry.register(
        LoadSkill(skill_loader)
    )
    mcp_manager = MCPManager(registry)
    detector = DangerousCommandDetector()
    permission_checker = PermissionChecker(
        detector=detector,
        sandbox=sandbox,
        mode = PermissionMode(args.permission_mode),
    )
    agent = Agent(
        client=client,
        registry=registry,
        context_window=config.context_window,
        permission_checker=permission_checker,
    ) 

    session_manager = SessionManager(
        sandbox.project_root,
    )

    if args.resume is None:
        session = session_manager.create()

        conversation = ConversationManager(
            on_message=session.append,
        )

    else:
        resume_result = session_manager.resume(
            args.resume
        )

        if resume_result is None:
            raise SystemExit(
                f"Session not found: {args.resume}"
            )

        session = resume_result.session

        conversation = ConversationManager(
            history=resume_result.messages,
            on_message=session.append,
        )

    def save_compact_boundary(
        boundary: CompactBoundary,
    ) -> None:
        record = make_compact_boundary(
            boundary.summary,
            boundary.keep,
        )
        session.append_record(record)

    try:
        if args.mcp_config is not None:
            server_configs = (
                load_mcp_server_configs(
                    args.mcp_config
                )
            )

            for server_config in server_configs:
                tool_names = await (
                    mcp_manager.connect_server(
                        server_config
                    )
                )

                print(
                    (
                        f"[mcp] connected "
                        f"{server_config.name} "
                        f"({len(tool_names)} tools)"
                    ),
                    file=sys.stderr,
                    flush=True,
                )

        if args.prompt is None:
            await run_tui(
                agent,
                conversation,
                session,
            )
            return


        if args.stream:
            async for event in agent.stream_to_completion(
                args.prompt,
                conversation=conversation,
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

                elif isinstance(event, CompactNotification):
                    if event.boundary is not None:
                        save_compact_boundary(
                            event.boundary
                        )

                    print(
                        f"\n[context] {event.message}",
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
                args.prompt,
                conversation=conversation,
                on_compact=save_compact_boundary,
            )
            print(answer)

    finally:
        try:
            await mcp_manager.close()
        finally:
            session.close()

if __name__ == "__main__":
        asyncio.run(main())
