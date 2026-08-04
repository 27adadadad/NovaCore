from __future__ import annotations
from pathlib import Path

import argparse
import asyncio
import sys

from novacore.client import DashScopeClient
from novacore.config import load_config
from novacore.tools import create_default_registry
from novacore.tool_search import (
    ToolSearch,
    restore_discovered_tools,
)
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
from novacore.context import (
    CompactBoundary,
    compact_conversation,
)
from novacore.mcp import MCPManager, load_mcp_server_configs
from novacore.skills import (
    LoadSkill,
    SkillLoader,
)
from novacore.agents import (
    AgentLoader,
    AgentTool,
    TaskManager,
    inject_task_notifications,
)
from novacore.worktree import WorktreeManager
from novacore.memory import (
    MemoryStoreError,
    MemoryStore,
    RecallMemory,
    Remember,
)
from novacore.teams import (
    Coordinator,
    acknowledge_team_notifications,
    collect_team_notifications,
    inject_team_notifications,
    register_team_tools,
)
from novacore.commands import (
    CommandContext,
    CommandRegistry,
    parse_command,
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
    memory_store = MemoryStore(
        sandbox.project_root
    )
    registry.register(
        RecallMemory(memory_store)
    )
    registry.register(
        Remember(memory_store)
    )
    registry.register(
        ToolSearch(registry)
    )
    skill_loader = SkillLoader(
        sandbox.project_root
    )

    skill_loader.load_all()

    registry.register(
        LoadSkill(skill_loader)
    )
    agent_loader = AgentLoader(
        sandbox.project_root
    )

    agent_loader.load_all()
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
    task_manager = TaskManager()
    worktree_manager = WorktreeManager(
        sandbox.project_root
    )
    session_manager = SessionManager(
        sandbox.project_root,
    )
    coordinator = Coordinator(
        work_dir=sandbox.project_root,
        parent_agent=agent,
        agent_loader=agent_loader,
        session_manager=session_manager,
        worktree_manager=worktree_manager,
    )

    register_team_tools(
        registry,
        coordinator,
        deferred=True,
    )
    registry.register(
        AgentTool(
            loader=agent_loader,
            parent_agent=agent,
            task_manager=task_manager,
            worktree_manager=worktree_manager,
        )
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

    try:
        memory_prompt = (
            memory_store.build_system_prompt()
        )
    except MemoryStoreError as exc:
        print(
            f"[memory] could not load: {exc}",
            file=sys.stderr,
            flush=True,
        )
    else:
        if memory_prompt:
            conversation.prepend_system_message(
                memory_prompt
            )

    restore_discovered_tools(
        registry,
        conversation.get_messages(),
    )

    def save_compact_boundary(
        boundary: CompactBoundary,
    ) -> None:
        record = make_compact_boundary(
            boundary.summary,
            boundary.keep,
        )
        session.append_record(record)

    async def compact_action() -> str:
        compact_event = await compact_conversation(
            conversation,
            agent.client,
            agent.context_window,
            manual=True,
        )

        if (
            compact_event is None
            or compact_event.boundary is None
        ):
            return "Context is too small to compact"

        save_compact_boundary(
            compact_event.boundary
        )
        return (
            "Context compacted "
            f"({compact_event.before_tokens:,} "
            "tokens before compaction)"
        )

    async def wait_and_inject_task_notifications(
    ) -> bool:
        await asyncio.gather(
            task_manager.wait_all(),
            coordinator.task_manager.wait_all(),
        )

        completed_tasks = (
            task_manager.poll_completed()
        )

        team_messages = await (
            collect_team_notifications(
                coordinator
            )
        )

        if not completed_tasks and not team_messages:
            return False

        inject_task_notifications(
            conversation,
            completed_tasks,
        )
        inject_team_notifications(
            conversation,
            team_messages,
        )
        acknowledge_team_notifications(
            coordinator,
            team_messages,
        )

        for task in completed_tasks:
            print(
                (
                    f"[task] {task.task_id} "
                    f"{task.name}: {task.status}"
                ),
                file=sys.stderr,
                flush=True,
            )

        for message in team_messages:
            print(
                (
                    f"[team] {message.task_id or '-'} "
                    f"from {message.sender_id}: "
                    f"{message.message_type.value}"
                ),
                file=sys.stderr,
                flush=True,
            )

        return True

    async def run_streaming_prompt(
        prompt: str,
    ) -> None:

        async for event in agent.stream_to_completion(
            prompt,
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

    try:
        # Team 恢复放在统一清理边界内，失败时也会关闭所有资源。
        restored_team = await (
            coordinator.restore_active_team()
        )

        if restored_team is not None:
            print(
                (
                    f"[team] restored {restored_team.name} "
                    f"({restored_team.team_id})"
                ),
                file=sys.stderr,
                flush=True,
            )

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

                # MCP 工具在连接后才完成注册，此时再恢复
                # Session 中曾经由 ToolSearch 激活的工具。
                restore_discovered_tools(
                    registry,
                    conversation.get_messages(),
                )

        if args.prompt is None:
            await run_tui(
                agent,
                conversation,
                session,
                task_manager,
                coordinator,
                memory_store,
            )
            return

        try:
            invocation = parse_command(args.prompt)
        except ValueError as exc:
            print(
                f"Command error: {exc}",
                file=sys.stderr,
            )
            return

        if invocation is not None:
            command_result = await CommandRegistry().execute(
                CommandContext(
                    conversation=conversation,
                    session_id=session.session_id,
                    compact=compact_action,
                    task_manager=task_manager,
                    memory_store=memory_store,
                    coordinator=coordinator,
                ),
                invocation,
            )
            output_stream = (
                sys.stderr
                if command_result.is_error
                else sys.stdout
            )
            print(
                command_result.content,
                file=output_stream,
            )
            return


        if args.stream:
            await run_streaming_prompt(
                args.prompt
            )

            while (
                await wait_and_inject_task_notifications()
            ):
                await run_streaming_prompt(
                    (
                        "请根据上面的后台任务通知，"
                        "继续完成当前任务。"
                    )
                )

        else:
            answer = await agent.run_to_completion(
                args.prompt,
                conversation=conversation,
                on_compact=save_compact_boundary,
            )
            print(answer)

            while (
                await wait_and_inject_task_notifications()
            ):
                answer = await agent.run_to_completion(
                    (
                        "请根据上面的后台任务通知，"
                        "继续完成当前任务。"
                    ),
                    conversation=conversation,
                    on_compact=save_compact_boundary,
                )

                restore_discovered_tools(
                    registry,
                    conversation.get_messages(),
                )
                print(answer)

    finally:
        try:
            await coordinator.shutdown()
        finally:
            try:
                await task_manager.shutdown()
            finally:
                try:
                    await mcp_manager.close()
                finally:
                    session.close()

if __name__ == "__main__":
        asyncio.run(main())
