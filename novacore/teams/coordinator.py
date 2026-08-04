from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from novacore.agent import Agent
from novacore.agents import (
    AgentLoader,
    AgentToolFilterError,
    TaskManager,
    build_agent_registry,
)
from novacore.conversation import (
    ConversationManager,
    Message,
)
from novacore.path_sandbox import PathSandbox
from novacore.permissions import (
    PermissionChecker,
    PermissionMode,
)
from novacore.session import Session, SessionManager
from novacore.teams.mailbox import Mailbox
from novacore.teams.models import (
    MailboxMessage,
    MessageType,
    SharedTask,
    SharedTaskStatus,
    Team,
    TeamStatus,
    Teammate,
    TeammateStatus,
)
from novacore.teams.store import (
    SharedTaskStore,
    TeamSnapshot,
    TeamStore,
)
from novacore.tools import create_worktree_registry
from novacore.worktree import (
    CleanupResult,
    WorktreeManager,
    generate_worktree_name,
)


class CoordinatorError(RuntimeError):
    """Coordinator 无法安全完成团队操作。"""


def _new_id(prefix: str) -> str:
    """生成适合路径和 JSON 主键使用的短 ID。"""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _utc_now() -> datetime:
    """返回可直接持久化的 UTC 时间。"""

    return datetime.now(timezone.utc)


class Coordinator:
    """管理一个进程内 Team 的持久状态与运行时对象。"""

    def __init__(
        self,
        work_dir: str | Path,
        parent_agent: Agent,
        agent_loader: AgentLoader,
        session_manager: SessionManager,
        worktree_manager: WorktreeManager,
        task_manager: TaskManager | None = None,
    ) -> None:
        self.work_dir = (
            Path(work_dir)
            .expanduser()
            .resolve()
        )
        self.parent_agent = parent_agent
        self.agent_loader = agent_loader
        self.session_manager = session_manager
        self.worktree_manager = worktree_manager

        # Teams 使用独立 TaskManager，避免消费普通后台 Agent 的完成队列。
        self.task_manager = (
            task_manager
            if task_manager is not None
            else TaskManager()
        )
        self.team_store = TeamStore(self.work_dir)

        self._team: Team | None = None
        self._teammates: dict[str, Teammate] = {}
        self._tasks: dict[str, SharedTask] = {}
        self._agents: dict[str, Agent] = {}
        self._conversations: dict[
            str,
            ConversationManager,
        ] = {}
        self._sessions: dict[str, Session] = {}
        self._background_to_shared: dict[str, str] = {}
        self._shared_to_background: dict[str, str] = {}
        self._pending_background_completions: set[str] = set()
        self._shutdown_interruptions: set[str] = set()
        self._task_store: SharedTaskStore | None = None
        self._mailbox: Mailbox | None = None
        self._lock = asyncio.Lock()
        self._persistence_failed = False

    @property
    def team(self) -> Team | None:
        """返回当前活动 Team 快照。"""

        return self._team

    def list_teammates(self) -> tuple[Teammate, ...]:
        """按创建顺序返回队友快照。"""

        return tuple(
            sorted(
                self._teammates.values(),
                key=lambda item: (
                    item.created_at,
                    item.teammate_id,
                ),
            )
        )

    def list_tasks(self) -> tuple[SharedTask, ...]:
        """按创建顺序返回共享任务快照。"""

        return tuple(
            sorted(
                self._tasks.values(),
                key=lambda item: (
                    item.created_at,
                    item.task_id,
                ),
            )
        )

    def get_teammate(
        self,
        teammate_id: str,
    ) -> Teammate | None:
        """按 ID 查询队友。"""

        return self._teammates.get(teammate_id)

    def get_task(
        self,
        task_id: str,
    ) -> SharedTask | None:
        """按 ID 查询共享任务。"""

        return self._tasks.get(task_id)

    def _require_team(self) -> Team:
        """取得当前 Team；没有活动 Team 时立即失败。"""

        if self._team is None:
            raise CoordinatorError(
                "no active team is loaded"
            )

        if self._team.status != TeamStatus.ACTIVE:
            raise CoordinatorError(
                "the current team is not active"
            )

        return self._team

    def _require_writable(self) -> None:
        """磁盘回滚失败后阻止继续覆盖可能损坏的数据。"""

        if self._persistence_failed:
            raise CoordinatorError(
                "team persistence is in an uncertain state; "
                "reload the coordinator before writing again"
            )

    def _snapshot(self) -> TeamSnapshot:
        """把当前 Team 和队友组合成一个持久化快照。"""

        team = self._require_team()
        return TeamSnapshot(
            team=team,
            teammates=self.list_teammates(),
        )

    def _save_team(self) -> None:
        """保存不涉及任务表的 Team 状态。"""

        self._require_writable()
        self.team_store.save(self._snapshot())

    def _save_tasks_and_team(
        self,
        old_tasks: tuple[SharedTask, ...],
    ) -> None:
        """跨两个 JSON 文件保存，并在第二步失败时回滚任务表。"""

        self._require_writable()

        if self._task_store is None:
            raise CoordinatorError(
                "task store is not initialized"
            )

        self._task_store.save(self.list_tasks())

        try:
            self.team_store.save(self._snapshot())
        except Exception:
            try:
                self._task_store.save(old_tasks)
            except Exception:
                self._persistence_failed = True
            raise

    def _build_runtime(
        self,
        teammate: Teammate,
        history: list[Message] | None = None,
        session: Session | None = None,
    ) -> tuple[Agent, ConversationManager]:
        """为一个队友构造受 Worktree 限制的 Agent 与 Conversation。"""

        definition = self.agent_loader.get(
            teammate.agent_type
        )
        if definition is None:
            raise CoordinatorError(
                "unknown teammate agent type: "
                f"{teammate.agent_type}"
            )

        try:
            safe_registry = create_worktree_registry(
                teammate.worktree.path
            )
            registry = build_agent_registry(
                safe_registry,
                definition,
            )
        except (AgentToolFilterError, ValueError) as exc:
            raise CoordinatorError(
                "could not build teammate tool registry: "
                f"{exc}"
            ) from exc

        checker = PermissionChecker(
            detector=(
                self.parent_agent
                .permission_checker
                .detector
            ),
            sandbox=PathSandbox(
                teammate.worktree.path
            ),
            mode=PermissionMode(
                definition.permission_mode
            ),
            enforce_sandbox=True,
        )
        agent = Agent(
            client=self.parent_agent.client,
            registry=registry,
            context_window=(
                self.parent_agent.context_window
            ),
            permission_checker=checker,
            max_iterations=definition.max_turns,
            trace_manager=(
                self.parent_agent.trace_manager
            ),
            agent_type=definition.agent_type,
            parent_trace=(
                self.parent_agent.current_trace
            ),
            hook_engine=self.parent_agent.hook_engine,
        )
        # SessionRecord 暂无 system 类型，系统提示在恢复时由 AgentDef 重建。
        conversation = ConversationManager()
        conversation.add_system_message(
            definition.system_prompt
        )
        conversation.add_system_message(
            "你是 Team 中的独立队友。所有文件工具都以你的 "
            "Git Worktree 为根目录；只处理 Coordinator 分配的任务。"
        )

        if history is not None:
            conversation.history.extend(history)

        if session is not None:
            conversation.on_message = session.append

        return agent, conversation

    async def create_team(
        self,
        name: str,
        lead_agent_id: str = "coordinator",
    ) -> Team:
        """创建并持久化当前进程唯一的活动 Team。"""

        async with self._lock:
            self._require_writable()

            if self._team is not None:
                raise CoordinatorError(
                    "a team is already loaded"
                )

            for team_id in self.team_store.list_team_ids():
                existing = self.team_store.load(team_id)
                if (
                    existing is not None
                    and existing.team.status
                    == TeamStatus.ACTIVE
                ):
                    raise CoordinatorError(
                        "an active team already exists on "
                        "disk; restore or close it before "
                        "creating another team"
                    )

            if not name.strip():
                raise CoordinatorError(
                    "team name must not be empty"
                )

            if not lead_agent_id.strip():
                raise CoordinatorError(
                    "lead_agent_id must not be empty"
                )

            team = Team(
                team_id=_new_id("team"),
                name=name.strip(),
                lead_agent_id=lead_agent_id.strip(),
            )
            task_store = SharedTaskStore(
                self.work_dir,
                team.team_id,
            )

            self._team = team
            self._task_store = task_store
            self._mailbox = Mailbox(
                self.work_dir,
                team.team_id,
            )

            try:
                task_store.save(())
                self.team_store.save(self._snapshot())
            except Exception:
                self._team = None
                self._task_store = None
                self._mailbox = None
                raise

            return team

    async def add_teammate(
        self,
        name: str,
        agent_type: str,
    ) -> Teammate:
        """为队友创建持久 Worktree、Session 和受限 Agent。"""

        async with self._lock:
            team = self._require_team()
            self._require_writable()

            if not name.strip():
                raise CoordinatorError(
                    "teammate name must not be empty"
                )

            definition = self.agent_loader.get(
                agent_type
            )
            if definition is None:
                raise CoordinatorError(
                    f"unknown agent type: {agent_type}"
                )

            teammate_id = _new_id("mate")
            worktree = None
            session = None

            try:
                worktree = await self.worktree_manager.create(
                    generate_worktree_name(
                        f"{name}-{teammate_id[-6:]}"
                    )
                )
                session = self.session_manager.create()
                teammate = Teammate(
                    teammate_id=teammate_id,
                    name=name.strip(),
                    agent_type=definition.agent_type,
                    session_id=session.session_id,
                    worktree=worktree,
                )
                agent, conversation = self._build_runtime(
                    teammate,
                    session=session,
                )
            except Exception:
                if session is not None:
                    session.close()
                if worktree is not None:
                    await self.worktree_manager.cleanup(
                        worktree.name
                    )
                raise

            old_team = team
            self._teammates[teammate_id] = teammate
            self._agents[teammate_id] = agent
            self._conversations[
                teammate_id
            ] = conversation
            self._sessions[teammate_id] = session
            self._team = replace(
                team,
                member_ids=(
                    *team.member_ids,
                    teammate_id,
                ),
            )

            try:
                self._save_team()
            except Exception:
                self._team = old_team
                self._teammates.pop(teammate_id, None)
                self._agents.pop(teammate_id, None)
                self._conversations.pop(teammate_id, None)
                self._sessions.pop(teammate_id, None)
                session.close()
                await self.worktree_manager.cleanup(
                    worktree.name
                )
                raise

            return teammate

    async def create_task(
        self,
        title: str,
        description: str = "",
    ) -> SharedTask:
        """创建尚未分配的共享任务。"""

        async with self._lock:
            self._require_team()
            self._require_writable()

            if not title.strip():
                raise CoordinatorError(
                    "task title must not be empty"
                )

            old_tasks = self.list_tasks()
            task = SharedTask(
                task_id=_new_id("task"),
                title=title.strip(),
                description=description.strip(),
            )
            self._tasks[task.task_id] = task

            try:
                self._save_tasks_and_team(old_tasks)
            except Exception:
                self._tasks.pop(task.task_id, None)
                raise

            return task

    async def assign_task(
        self,
        task_id: str,
        teammate_id: str,
    ) -> SharedTask:
        """把一个 pending 任务绑定到当前空闲队友。"""

        async with self._lock:
            self._require_team()
            self._require_writable()

            task = self._tasks.get(task_id)
            teammate = self._teammates.get(
                teammate_id
            )

            if task is None:
                raise CoordinatorError(
                    f"unknown shared task: {task_id}"
                )
            if teammate is None:
                raise CoordinatorError(
                    f"unknown teammate: {teammate_id}"
                )
            if task.status != SharedTaskStatus.PENDING:
                raise CoordinatorError(
                    "only pending tasks can be assigned"
                )
            if (
                teammate.status != TeammateStatus.IDLE
                or teammate.current_task_id is not None
            ):
                raise CoordinatorError(
                    "the teammate is not available"
                )

            old_tasks = self.list_tasks()
            old_task = task
            old_teammate = teammate
            now = _utc_now()
            task = replace(
                task,
                status=SharedTaskStatus.ASSIGNED,
                assignee_id=teammate_id,
                updated_at=now,
            )
            teammate = replace(
                teammate,
                current_task_id=task_id,
                error="",
            )
            self._tasks[task_id] = task
            self._teammates[teammate_id] = teammate

            try:
                self._save_tasks_and_team(old_tasks)
            except Exception:
                self._tasks[task_id] = old_task
                self._teammates[
                    teammate_id
                ] = old_teammate
                raise

            return task

    def _task_prompt(
        self,
        task: SharedTask,
    ) -> str:
        """把长期任务记录转换为本次 Agent 调用的 prompt。"""

        if task.description:
            return (
                f"任务：{task.title}\n\n"
                f"详细要求：\n{task.description}"
            )

        return f"任务：{task.title}"

    def _mailbox_participants(
        self,
    ) -> set[str]:
        """返回当前 Team 中允许收发消息的全部身份。"""

        team = self._require_team()
        return {
            team.lead_agent_id,
            *team.member_ids,
        }

    def _validate_mail_route(
        self,
        sender_id: str,
        recipient_id: str,
    ) -> None:
        """只允许 Coordinator 与 Teammate 之间点对点通信。"""

        team = self._require_team()
        participants = self._mailbox_participants()

        if (
            sender_id not in participants
            or recipient_id not in participants
        ):
            raise CoordinatorError(
                "mailbox sender and recipient must "
                "belong to the current team"
            )

        lead = team.lead_agent_id
        if not (
            sender_id == lead
            and recipient_id != lead
        ) and not (
            sender_id != lead
            and recipient_id == lead
        ):
            raise CoordinatorError(
                "mailbox only supports coordinator-to-"
                "teammate communication"
            )

    def send_message(
        self,
        sender_id: str,
        recipient_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        task_id: str | None = None,
    ) -> MailboxMessage:
        """向一个合法收件人的 inbox 写入消息。"""

        self._require_writable()
        self._validate_mail_route(
            sender_id,
            recipient_id,
        )

        if not content:
            raise CoordinatorError(
                "mailbox content must not be empty"
            )

        if (
            task_id is not None
            and task_id not in self._tasks
        ):
            raise CoordinatorError(
                f"unknown shared task: {task_id}"
            )

        if self._mailbox is None:
            raise CoordinatorError(
                "mailbox is not initialized"
            )

        message = MailboxMessage(
            message_id=_new_id("msg"),
            sender_id=sender_id,
            recipient_id=recipient_id,
            message_type=message_type,
            content=content,
            task_id=task_id,
        )
        self._mailbox.send(message)
        return message

    def list_messages(
        self,
        recipient_id: str,
    ) -> tuple[MailboxMessage, ...]:
        """查看某个 Team 成员尚未确认的消息。"""

        if recipient_id not in self._mailbox_participants():
            raise CoordinatorError(
                "mailbox recipient must belong to "
                "the current team"
            )

        if self._mailbox is None:
            raise CoordinatorError(
                "mailbox is not initialized"
            )

        return self._mailbox.list_pending(
            recipient_id
        )

    def acknowledge_message(
        self,
        recipient_id: str,
        message_id: str,
    ) -> MailboxMessage:
        """把已处理消息从 inbox 原子移动到 processed。"""

        if recipient_id not in self._mailbox_participants():
            raise CoordinatorError(
                "mailbox recipient must belong to "
                "the current team"
            )

        if self._mailbox is None:
            raise CoordinatorError(
                "mailbox is not initialized"
            )

        return self._mailbox.acknowledge(
            recipient_id,
            message_id,
        )

    async def start_task(
        self,
        task_id: str,
    ) -> str:
        """持久化 running 状态后启动队友后台 Agent。"""

        async with self._lock:
            team = self._require_team()
            self._require_writable()
            task = self._tasks.get(task_id)

            if task is None:
                raise CoordinatorError(
                    f"unknown shared task: {task_id}"
                )
            if task.status != SharedTaskStatus.ASSIGNED:
                raise CoordinatorError(
                    "only assigned tasks can be started"
                )
            if task.assignee_id is None:
                raise CoordinatorError(
                    "assigned task has no assignee"
                )

            teammate = self._teammates.get(
                task.assignee_id
            )
            agent = self._agents.get(task.assignee_id)
            conversation = self._conversations.get(
                task.assignee_id
            )
            session = self._sessions.get(
                task.assignee_id
            )

            if teammate is None:
                raise CoordinatorError(
                    "task assignee is missing"
                )
            if (
                teammate.status != TeammateStatus.IDLE
                or teammate.current_task_id != task_id
            ):
                raise CoordinatorError(
                    "task assignee is not ready"
                )
            if (
                agent is None
                or conversation is None
                or session is None
            ):
                raise CoordinatorError(
                    "teammate runtime is not available"
                )

            old_tasks = self.list_tasks()
            old_task = task
            old_teammate = teammate
            now = _utc_now()
            task = replace(
                task,
                status=SharedTaskStatus.RUNNING,
                updated_at=now,
                result="",
                error="",
            )
            teammate = replace(
                teammate,
                status=TeammateStatus.RUNNING,
                error="",
            )
            self._tasks[task_id] = task
            self._teammates[
                teammate.teammate_id
            ] = teammate

            try:
                self._save_tasks_and_team(old_tasks)
            except Exception:
                self._tasks[task_id] = old_task
                self._teammates[
                    teammate.teammate_id
                ] = old_teammate
                raise

            prompt = self._task_prompt(task)

            try:
                instruction = self.send_message(
                    sender_id=team.lead_agent_id,
                    recipient_id=teammate.teammate_id,
                    content=prompt,
                    message_type=(
                        MessageType.INSTRUCTION
                    ),
                    task_id=task_id,
                )
                # 内部 runner 已经取得指令，因此立即归档该 inbox 项。
                self.acknowledge_message(
                    teammate.teammate_id,
                    instruction.message_id,
                )
                background_id = self.task_manager.launch(
                    agent=agent,
                    conversation=conversation,
                    prompt=prompt,
                    name=(
                        f"team:{team.team_id}:"
                        f"{teammate.name}"
                    ),
                    on_compact=session.append_record,
                )
            except Exception as exc:
                failed_task = replace(
                    task,
                    status=SharedTaskStatus.FAILED,
                    error=(
                        "could not start teammate task: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    updated_at=_utc_now(),
                )
                failed_teammate = replace(
                    teammate,
                    status=TeammateStatus.IDLE,
                    current_task_id=None,
                    error=failed_task.error,
                )
                current_tasks = self.list_tasks()
                self._tasks[task_id] = failed_task
                self._teammates[
                    teammate.teammate_id
                ] = failed_teammate

                try:
                    self._save_tasks_and_team(
                        current_tasks
                    )
                except Exception:
                    self._persistence_failed = True
                    raise

                raise CoordinatorError(
                    failed_task.error
                ) from exc

            self._background_to_shared[
                background_id
            ] = task_id
            self._shared_to_background[
                task_id
            ] = background_id
            return background_id

    def _completion_state(
        self,
        shared_task: SharedTask,
        background_id: str,
    ) -> tuple[
        SharedTaskStatus,
        TeammateStatus,
        str,
        str,
        MessageType,
    ]:
        """把 TaskManager 状态翻译成 Teams 的长期状态。"""

        background = self.task_manager.get(
            background_id
        )
        if background is None:
            return (
                SharedTaskStatus.INTERRUPTED,
                TeammateStatus.INTERRUPTED,
                "",
                "background task record disappeared",
                MessageType.STATUS,
            )

        if background.status == "completed":
            return (
                SharedTaskStatus.COMPLETED,
                TeammateStatus.IDLE,
                background.result,
                "",
                MessageType.RESULT,
            )

        if background.status == "failed":
            return (
                SharedTaskStatus.FAILED,
                TeammateStatus.IDLE,
                "",
                background.error,
                MessageType.STATUS,
            )

        if background.status == "cancelled":
            if shared_task.task_id in self._shutdown_interruptions:
                return (
                    SharedTaskStatus.INTERRUPTED,
                    TeammateStatus.INTERRUPTED,
                    "",
                    "task was interrupted by coordinator shutdown",
                    MessageType.STATUS,
                )

            return (
                SharedTaskStatus.CANCELLED,
                TeammateStatus.IDLE,
                "",
                background.error,
                MessageType.STATUS,
            )

        raise CoordinatorError(
            "background task is not complete: "
            f"{background_id}"
        )

    async def poll_completed(
        self,
    ) -> tuple[SharedTask, ...]:
        """收集后台结果，持久化状态，并投递完成通知。"""

        async with self._lock:
            self._require_team()
            self._require_writable()

            for background in self.task_manager.poll_completed():
                self._pending_background_completions.add(
                    background.task_id
                )

            completed: list[SharedTask] = []

            for background_id in tuple(
                self._pending_background_completions
            ):
                task_id = self._background_to_shared.get(
                    background_id
                )
                if task_id is None:
                    self._pending_background_completions.discard(
                        background_id
                    )
                    continue

                task = self._tasks.get(task_id)
                if task is None or task.assignee_id is None:
                    raise CoordinatorError(
                        "background task mapping is invalid"
                    )

                teammate = self._teammates.get(
                    task.assignee_id
                )
                if teammate is None:
                    raise CoordinatorError(
                        "completed task assignee is missing"
                    )

                (
                    task_status,
                    teammate_status,
                    result,
                    error,
                    message_type,
                ) = self._completion_state(
                    task,
                    background_id,
                )
                old_tasks = self.list_tasks()
                old_task = task
                old_teammate = teammate
                task = replace(
                    task,
                    status=task_status,
                    result=result,
                    error=error,
                    updated_at=_utc_now(),
                )
                teammate = replace(
                    teammate,
                    status=teammate_status,
                    current_task_id=None,
                    error=error,
                )
                self._tasks[task_id] = task
                self._teammates[
                    teammate.teammate_id
                ] = teammate

                try:
                    self._save_tasks_and_team(old_tasks)
                except Exception:
                    self._tasks[task_id] = old_task
                    self._teammates[
                        teammate.teammate_id
                    ] = old_teammate
                    raise

                content = (
                    result
                    if result
                    else (
                        f"任务 {task.title} 状态："
                        f"{task.status.value}。{error}"
                    )
                )
                self.send_message(
                    sender_id=teammate.teammate_id,
                    recipient_id=(
                        self._require_team()
                        .lead_agent_id
                    ),
                    content=content,
                    message_type=message_type,
                    task_id=task_id,
                )

                self._pending_background_completions.discard(
                    background_id
                )
                self._background_to_shared.pop(
                    background_id,
                    None,
                )
                self._shared_to_background.pop(
                    task_id,
                    None,
                )
                self._shutdown_interruptions.discard(
                    task_id
                )
                completed.append(task)

            return tuple(completed)

    async def cancel_task(
        self,
        task_id: str,
    ) -> bool:
        """请求取消运行任务，并等待 TaskManager 完成清理。"""

        background_id = self._shared_to_background.get(
            task_id
        )
        if background_id is None:
            return False

        if not self.task_manager.cancel(background_id):
            return False

        while True:
            background = self.task_manager.get(
                background_id
            )
            if (
                background is None
                or background.status != "running"
            ):
                break
            await asyncio.sleep(0)

        await self.poll_completed()
        return True

    async def shutdown(self) -> None:
        """中断运行任务并关闭 Session，但不关闭 Team。"""

        self._shutdown_interruptions.update(
            task_id
            for task_id in self._shared_to_background
        )
        await self.task_manager.shutdown()

        if (
            self._team is not None
            and self._team.status == TeamStatus.ACTIVE
        ):
            await self.poll_completed()

        for session in self._sessions.values():
            session.close()

        self._sessions.clear()

    async def close_team(
        self,
    ) -> tuple[CleanupResult, ...]:
        """永久关闭空闲 Team，并保守清理各队友 Worktree。"""

        # TaskManager 可能已经结束，但完成状态仍在队列里等待消费。
        await self.poll_completed()

        async with self._lock:
            team = self._require_team()
            self._require_writable()

            if self.task_manager.has_running():
                raise CoordinatorError(
                    "cannot close a team with running tasks"
                )

            old_team = team
            old_teammates = dict(self._teammates)
            self._team = replace(
                team,
                status=TeamStatus.CLOSED,
            )
            self._teammates = {
                teammate_id: replace(
                    teammate,
                    status=TeammateStatus.STOPPED,
                    current_task_id=None,
                )
                for teammate_id, teammate
                in self._teammates.items()
            }

            try:
                self.team_store.save(
                    TeamSnapshot(
                        team=self._team,
                        teammates=self.list_teammates(),
                    )
                )
            except Exception:
                self._team = old_team
                self._teammates = old_teammates
                raise

            for session in self._sessions.values():
                session.close()
            self._sessions.clear()

            worktrees = tuple(
                teammate.worktree
                for teammate in old_teammates.values()
            )

        results: list[CleanupResult] = []
        for worktree in worktrees:
            results.append(
                await self.worktree_manager.cleanup(
                    worktree.name
                )
            )

        return tuple(results)

    def _validate_restored_tasks(self) -> None:
        """验证 Team、Teammate 与 SharedTask 的引用关系。"""

        team = self._require_team()
        member_ids = set(team.member_ids)

        for task in self._tasks.values():
            if (
                task.assignee_id is not None
                and task.assignee_id not in member_ids
            ):
                raise CoordinatorError(
                    "shared task references an unknown "
                    f"teammate: {task.task_id}"
                )

            if task.status in {
                SharedTaskStatus.ASSIGNED,
                SharedTaskStatus.RUNNING,
            } and task.assignee_id is None:
                raise CoordinatorError(
                    "assigned or running task has no "
                    f"assignee: {task.task_id}"
                )

            if task.status in {
                SharedTaskStatus.ASSIGNED,
                SharedTaskStatus.RUNNING,
            }:
                teammate = self._teammates.get(
                    task.assignee_id or ""
                )
                if (
                    teammate is None
                    or teammate.current_task_id
                    != task.task_id
                ):
                    raise CoordinatorError(
                        "active task and teammate current "
                        f"task do not match: {task.task_id}"
                    )

        claimed_tasks: set[str] = set()
        for teammate in self._teammates.values():
            current_task_id = teammate.current_task_id
            if current_task_id is None:
                continue

            task = self._tasks.get(current_task_id)
            if task is None:
                raise CoordinatorError(
                    "teammate references an unknown "
                    f"task: {teammate.teammate_id}"
                )
            if task.assignee_id != teammate.teammate_id:
                raise CoordinatorError(
                    "teammate and task assignee do not "
                    f"match: {current_task_id}"
                )
            if current_task_id in claimed_tasks:
                raise CoordinatorError(
                    "multiple teammates claim the same "
                    f"task: {current_task_id}"
                )
            claimed_tasks.add(current_task_id)

    def _mark_interrupted_after_restart(self) -> None:
        """把进程退出时仍在运行的记录改为 interrupted。"""

        for task_id, task in tuple(
            self._tasks.items()
        ):
            if task.status != SharedTaskStatus.RUNNING:
                continue

            self._tasks[task_id] = replace(
                task,
                status=SharedTaskStatus.INTERRUPTED,
                error=(
                    "task was interrupted because the "
                    "previous process stopped"
                ),
                updated_at=_utc_now(),
            )

        for teammate_id, teammate in tuple(
            self._teammates.items()
        ):
            if teammate.status != TeammateStatus.RUNNING:
                continue

            self._teammates[teammate_id] = replace(
                teammate,
                status=TeammateStatus.INTERRUPTED,
                current_task_id=None,
                error=(
                    "teammate was interrupted because "
                    "the previous process stopped"
                ),
            )

    async def restore_active_team(
        self,
    ) -> Team | None:
        """从磁盘恢复唯一的活动 Team，不自动重启旧任务。"""

        async with self._lock:
            self._require_writable()

            if self._team is not None:
                raise CoordinatorError(
                    "a team is already loaded"
                )
            if self.task_manager.has_running():
                raise CoordinatorError(
                    "cannot restore while background "
                    "tasks are running"
                )

            active_snapshots: list[TeamSnapshot] = []
            for team_id in self.team_store.list_team_ids():
                snapshot = self.team_store.load(team_id)
                if (
                    snapshot is not None
                    and snapshot.team.status
                    == TeamStatus.ACTIVE
                ):
                    active_snapshots.append(snapshot)

            if not active_snapshots:
                return None

            if len(active_snapshots) != 1:
                raise CoordinatorError(
                    "multiple active teams were found; "
                    "manual recovery is required"
                )

            snapshot = active_snapshots[0]
            team = snapshot.team
            task_store = SharedTaskStore(
                self.work_dir,
                team.team_id,
            )
            tasks = task_store.load()

            self._team = team
            self._teammates = {
                teammate.teammate_id: teammate
                for teammate in snapshot.teammates
            }
            self._tasks = {
                task.task_id: task
                for task in tasks
            }
            self._task_store = task_store
            self._mailbox = Mailbox(
                self.work_dir,
                team.team_id,
            )

            try:
                self._validate_restored_tasks()
                self._mark_interrupted_after_restart()

                for teammate_id, teammate in tuple(
                    self._teammates.items()
                ):
                    resume_result = None

                    try:
                        await self.worktree_manager.adopt(
                            teammate.worktree
                        )
                        resume_result = (
                            self.session_manager.resume(
                                teammate.session_id
                            )
                        )
                        if resume_result is None:
                            raise CoordinatorError(
                                "teammate session is missing"
                            )

                        agent, conversation = (
                            self._build_runtime(
                                teammate,
                                history=(
                                    resume_result.messages
                                ),
                                session=(
                                    resume_result.session
                                ),
                            )
                        )
                    except Exception as exc:
                        if resume_result is not None:
                            resume_result.session.close()

                        self._teammates[
                            teammate_id
                        ] = replace(
                            self._teammates[teammate_id],
                            status=(
                                TeammateStatus.INTERRUPTED
                            ),
                            current_task_id=None,
                            error=(
                                "could not restore teammate "
                                f"runtime: {type(exc).__name__}: "
                                f"{exc}"
                            ),
                        )

                        for task_id, task in tuple(
                            self._tasks.items()
                        ):
                            if (
                                task.assignee_id == teammate_id
                                and task.status
                                == SharedTaskStatus.ASSIGNED
                            ):
                                self._tasks[task_id] = replace(
                                    task,
                                    status=(
                                        SharedTaskStatus
                                        .INTERRUPTED
                                    ),
                                    error=(
                                        "assignee runtime could "
                                        "not be restored"
                                    ),
                                    updated_at=_utc_now(),
                                )
                        continue

                    self._agents[teammate_id] = agent
                    self._conversations[
                        teammate_id
                    ] = conversation
                    self._sessions[
                        teammate_id
                    ] = resume_result.session

                self._save_tasks_and_team(tasks)
            except Exception:
                for session in self._sessions.values():
                    session.close()

                self._team = None
                self._teammates.clear()
                self._tasks.clear()
                self._agents.clear()
                self._conversations.clear()
                self._sessions.clear()
                self._task_store = None
                self._mailbox = None
                raise

            return self._team

    async def resume_teammate(
        self,
        teammate_id: str,
    ) -> Teammate:
        """显式把已恢复且无任务的 interrupted 队友设为 idle。"""

        async with self._lock:
            self._require_team()
            self._require_writable()
            teammate = self._teammates.get(
                teammate_id
            )

            if teammate is None:
                raise CoordinatorError(
                    f"unknown teammate: {teammate_id}"
                )
            if teammate.status != TeammateStatus.INTERRUPTED:
                raise CoordinatorError(
                    "only interrupted teammates can be resumed"
                )
            if teammate.current_task_id is not None:
                raise CoordinatorError(
                    "teammate still owns an unfinished task"
                )
            if (
                teammate_id not in self._agents
                or teammate_id not in self._conversations
                or teammate_id not in self._sessions
            ):
                raise CoordinatorError(
                    "teammate runtime was not restored"
                )

            old_teammate = teammate
            teammate = replace(
                teammate,
                status=TeammateStatus.IDLE,
                error="",
            )
            self._teammates[teammate_id] = teammate

            try:
                self._save_team()
            except Exception:
                self._teammates[
                    teammate_id
                ] = old_teammate
                raise

            return teammate
