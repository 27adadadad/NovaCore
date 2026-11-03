"""Host-bound Skill entry: model parameters never constitute spending consent."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import sys
import uuid

from pydantic import BaseModel, ConfigDict, Field

from novacore import pr_proposer as pp
from novacore.proposal_agents import run_agent_pair
from novacore.proposal_review import prepare_proposal
from novacore.tools import ToolResult


def source_is_clean(repo, files):
    """Compare approved files without Git diff/status clean-filter execution."""
    from novacore.pr_source import _path_reason
    for name in files:
        if _path_reason(name) or ':' in name or '\\' in name:
            return False
        path = repo / name
        if not path.resolve().is_relative_to(repo) or any(
                p.is_symlink() for p in (path, *path.parents) if p != repo.parent):
            return False
        tree = pp.git(repo, 'ls-tree', 'HEAD', '--', name).split()
        index = pp.git(repo, 'ls-files', '--stage', '--', name).split()
        if len(tree) < 3 or len(index) < 3 or tree[0] != b'100644' or index[:3] != [tree[0], tree[2], b'0']:
            return False
        baseline = pp.git(repo, 'cat-file', 'blob', 'HEAD:' + name)
        if path.stat().st_size > 65536:
            return False
        # Windows checkout CRLF is not a semantic user edit. No other filter
        # transformation is accepted; the immutable candidate uses Git bytes.
        if path.read_bytes().replace(b'\r\n', b'\n') != baseline.replace(b'\r\n', b'\n'):
            return False
    return True


class ProposalReviewParams(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: str = Field(min_length=1, max_length=8000, description='用户确认的具体修改需求')
    allow_files: list[str] = Field(min_length=1, max_length=5,
                                   description='用户批准的1至5个现有文件，相对项目根目录的路径')


async def terminal_consent(scope):
    """Out-of-band user input; never supplied by a model tool argument."""
    if not sys.stdin.isatty():
        return False
    print('\n[双 Agent 授权] 以下任务将使用最多10次额外模型请求（主对话请求另计）。'
          '\n只生成独立候选，不覆盖原文件，不提交、推送或合并。', file=sys.stderr)
    # ASCII JSON also escapes untrusted terminal control characters.
    print(json.dumps(scope, ensure_ascii=True, indent=2), file=sys.stderr, flush=True)
    try:
        return (await asyncio.to_thread(input, '本次同意请输入 RUN，其他输入取消：')).strip() == 'RUN'
    except (EOFError, OSError):
        return False


class RunProposalReview:
    name = 'RunProposalReview'
    category = 'write'
    params_model = ProposalReviewParams
    description = ('先生成候选再由独立Reviewer审核。使用前加载proposal-review Skill。'
                   '只处理当前项目批准的现有文件，终端另行授权最多10次额外模型请求；'
                   '不修改原文件，不发布。不能通过工具参数授予付费权限。')

    def __init__(self, work_dir, *, output_root=None, confirm=None, client_factory=None):
        self.work_dir = Path(work_dir).resolve()
        self.output_root = Path(output_root or Path.home() / '.novacore' / 'proposals').resolve()
        self.confirm = confirm
        self.client_factory = client_factory
        self.lock = asyncio.Lock()

    def get_schema(self):
        return {'type': 'function', 'function': {
            'name': RunProposalReview.name, 'description': RunProposalReview.description,
            'parameters': ProposalReviewParams.model_json_schema()}}

    async def execute(self, params):
        def reply(status, *, error=False, **data):
            return ToolResult(output=json.dumps({'status': status, **data}, ensure_ascii=True), is_error=error)
        if self.lock.locked():
            return reply('busy', error=True)
        async with self.lock:
            if self.confirm is None:
                return reply('authorization_unavailable', error=True)
            clients = []
            job = None
            try:
                # prepare_proposal checks paths; do not silently use committed bytes
                # when the user's approved file has uncommitted edits.
                if not source_is_clean(self.work_dir, params.allow_files):
                    return reply('uncommitted_allowed_files', error=True)
                if self.output_root == self.work_dir or self.work_dir in self.output_root.parents:
                    return reply('output_must_be_external', error=True)
                self.output_root.mkdir(parents=True, exist_ok=True)
                job = self.output_root / ('proposal-' + uuid.uuid4().hex)
                state = prepare_proposal(self.work_dir, params.task, params.allow_files, job)
                scope = {'task': params.task, 'allow_files': list(params.allow_files),
                         'repo': str(self.work_dir), 'job': str(job), 'head_sha': state['head_sha'],
                         'max_extra_requests': 10, 'max_turns_per_agent': 5}
                # Strict bool: a truthy object/string is NOT consent.
                if await self.confirm(scope) is not True:
                    pp.save(job / 'entry-result.json', {'status': 'authorization_denied', 'model_calls': 0})
                    return reply('authorization_denied', job=str(job), model_calls=0)
                # Revalidate after the human prompt, before constructing clients.
                if not source_is_clean(self.work_dir, params.allow_files):
                    return reply('source_changed_during_authorization', error=True, job=str(job))
                current, snapshot, _ = pp.workspace_state(job)
                pp.source_version(current, snapshot)
                factory = self.client_factory
                if factory is None:
                    from novacore.config import load_config
                    from novacore.proposal_agents import AgentModelClient
                    config = load_config()
                    factory = lambda: AgentModelClient(config)
                for _ in range(2):
                    clients.append(factory())
                result = await run_agent_pair(job, *clients, max_requests=10, max_rounds=5)
                pp.save(job / 'entry-result.json', result)
                return reply(result['status'], error=result['status'] not in {
                    'reviewed_no_findings', 'awaiting_human_selection'},
                    job=str(job), result=result, patch=str(job / 'changes.patch'),
                    review=str(job / 'agent-review.json'),
                    transcripts=[str(job / f'{role}-transcript.jsonl') for role in ('proposer', 'reviewer')])
            except asyncio.CancelledError:
                if job is not None and job.is_dir():
                    pp.save(job / 'entry-result.json', {'status': 'cancelled', 'no_automatic_retry': True})
                raise
            except Exception:
                return reply('workflow_unavailable', error=True, job=str(job) if job else None,
                             reason='Inspect local scope and records; no automatic retry.')
            finally:
                for client in clients:
                    try:
                        close = getattr(client, 'close', None) or getattr(getattr(client, 'sdk', None), 'close', None)
                        if close:
                            result = close()
                            if inspect.isawaitable(result):
                                await result
                    except Exception:
                        pass  # Never expose raw transport errors or retry model requests.
