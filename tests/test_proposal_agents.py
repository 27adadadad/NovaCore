"""Offline repeat-execution regression; no credentials or network required."""
import asyncio
import json
import subprocess

import pytest

from novacore.client import ClientResponse, ToolCall
from novacore.pr_source import ReviewError
from novacore.proposal_agents import run_agent_pair
from novacore.proposal_review import prepare_proposal


class FakeProposer:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return ClientResponse(tool_calls=[ToolCall(
                'write-1', 'WriteFile', {'file_path': 'app.py', 'content': 'x=1\n'})])
        return ClientResponse(text='{"status":"candidate_ready"}')


class FakeReviewer:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        assert 'WriteFile' not in {t['function']['name'] for t in tools}
        if self.calls == 1:
            return ClientResponse(tool_calls=[
                ToolCall('diff-1', 'GetDiff', {}),
                ToolCall('check-1', 'CheckCandidate', {}),
            ])
        return ClientResponse(text='{"verdict":"no_findings","findings":[]}')


def test_repeat_job_does_not_spend_again(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init', '-q')
    git('config', 'core.autocrlf', 'false')
    git('config', 'core.hooksPath', str(tmp_path / 'no-hooks'))
    (repo / 'app.py').write_bytes(b'x=2\n')
    git('add', 'app.py')
    git('-c', 'user.name=Offline Fixture', '-c', 'user.email=offline@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
    job = tmp_path / 'job'
    prepare_proposal(repo, 'Set x to 1', ['app.py'], job)

    proposer, reviewer = FakeProposer(), FakeReviewer()
    result = asyncio.run(run_agent_pair(job, proposer, reviewer))
    # Prove the first invocation really completed, rather than testing an
    # already-failed job whose clients were never called.
    assert result['status'] == 'reviewed_no_findings'
    assert (proposer.calls, reviewer.calls) == (2, 2)
    assert (repo / 'app.py').read_bytes() == b'x=2\n'
    assert (job / 'worktree/app.py').read_bytes() == b'x=1\n'
    record_before = (job / 'agent-run.json').read_bytes()
    assert json.loads(record_before)['calls'] == {'proposer': 2, 'reviewer': 2}

    # Recreate clients and reopen the same persisted job, as after restarting
    # a caller. The durable job guard must reject before either client runs.
    restarted_proposer, restarted_reviewer = FakeProposer(), FakeReviewer()
    with pytest.raises(ReviewError, match='fresh task job'):
        asyncio.run(run_agent_pair(job, restarted_proposer, restarted_reviewer))
    assert (restarted_proposer.calls, restarted_reviewer.calls) == (0, 0)
    assert (proposer.calls, reviewer.calls) == (2, 2)
    assert (job / 'agent-run.json').read_bytes() == record_before
    assert (repo / 'app.py').read_bytes() == b'x=2\n'
    assert (job / 'worktree/app.py').read_bytes() == b'x=1\n'
