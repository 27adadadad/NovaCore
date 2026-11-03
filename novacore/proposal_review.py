"""Task -> initial candidate -> independent evidence -> independent review."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import uuid

from novacore import pr_proposer as pp
from novacore.pr_source import ReviewError, _path_reason, _sha


def prepare_proposal(repo, task, files, output):
    """No prior reviewer report and no model call are required for an initial task."""
    repo, output = Path(repo).resolve(), Path(output).resolve()
    if not isinstance(task, str) or not task.strip() or len(task) > 8000:
        raise ReviewError('Provide a nonempty task of at most 8000 characters')
    if not files or len(files) > 5 or any(not isinstance(n, str) for n in files):
        raise ReviewError('Explicitly allow one to five existing files')
    if len({n.casefold() for n in files}) != len(files):
        raise ReviewError('Duplicate or case-colliding paths are not allowed')
    if any(_path_reason(n) or ':' in n or '\\' in n for n in files):
        raise ReviewError('Unsafe, sensitive or generated paths are not allowed')
    if output.exists() or output == repo or repo in output.parents:
        raise ReviewError('Use a new output directory outside the source checkout')
    head = _sha(pp.git(repo, 'rev-parse', 'HEAD').decode().strip())
    entries = {}
    total = 0
    for name in files:
        mode = pp.git(repo, 'ls-tree', head, '--', name).split(b' ', 1)[0]
        obj = head + ':' + name
        if mode != b'100644' or int(pp.git(repo, 'cat-file', '-s', obj)) > 65536:
            raise ReviewError('Only existing, regular non-executable files up to 64 KiB are supported')
        raw = pp.git(repo, 'cat-file', 'blob', obj)
        if b'\0' in raw:
            raise ReviewError('Binary content is unsupported')
        try:
            content = raw.decode('utf-8')
        except UnicodeError:
            raise ReviewError('Only UTF-8 source is supported') from None
        total += len(raw)
        entries[name] = {'file': name, 'previous_file': name, 'status': 'modified',
                         'before': content, 'after': content, 'patch': ''}
    if total > 65536:
        raise ReviewError('Total allowed source exceeds 64 KiB')
    snapshot = {
        'pr_url': 'local-task://' + uuid.uuid4().hex,
        'base_sha': head, 'head_sha': head, 'merge_base_sha': head,
        'metadata': {'title': 'Initial user task', 'body': task},
        'files': list(entries.values()),
        'coverage': {'status': 'complete', 'stale': False, 'total_files': len(entries),
                     'included_files': len(entries), 'skipped': [],
                     'scope': 'Explicitly allowed task files only; not a whole-repository review.'}}
    return pp.materialize_job(snapshot, repo, entries, [], output, job_kind='task_proposal')


async def run_proposal_review(job, proposer_client, reviewer_client):
    """At most one proposal and one review, in that order. Never auto-publish."""
    job = Path(job)
    state, snapshot, _ = pp.workspace_state(job)
    if (state.get('job_kind') != 'task_proposal' or state['status'] != 'prepared'
            or state['proposal_attempts'] or state['rereview_attempts']):
        raise ReviewError('A fresh task-proposal job is required')
    pp.source_version(state, snapshot)
    result = {'scope': 'initial proposal followed by independent candidate review',
              'status': 'started', 'calls': {'proposer': 0, 'reviewer': 0},
              'max_complete_invocations': 2, 'events': [],
              'publication': 'not requested; no commit, push or merge'}
    # Exclusive durable slot also prevents concurrent duplicate invocations.
    with (job / 'pipeline.json').open('x', encoding='utf-8') as f:
        json.dump(result, f)

    class CountedClient:
        def __init__(self, role, client):
            self.role, self.client = role, client

        async def complete(self, messages, tools):
            if result['calls'][self.role]:
                raise ReviewError('Role request budget exhausted')
            result['calls'][self.role] += 1
            result['events'].append(self.role)
            pp.save(job / 'pipeline.json', result)
            return await self.client.complete(messages=messages, tools=tools)

    proposed = await pp.propose_fix(job, CountedClient('proposer', proposer_client))
    result['proposal_status'] = proposed['status']
    if proposed['status'] != 'candidate_ready':
        result['status'] = 'proposal_not_ready'
        pp.save(job / 'pipeline.json', result)
        return result
    pp.source_version(proposed, snapshot)
    reviewed = await pp.review_fix(job, CountedClient('reviewer', reviewer_client))
    result['review_status'] = reviewed['model_status']
    result['verdict'] = reviewed['verdict']
    result['candidate_hashes'] = reviewed.get('candidate_hashes', {})
    if reviewed['model_status'] != 'completed':
        result['status'] = 'review_inconclusive'
    elif reviewed['verdict'] == 'request_changes':
        result['status'] = 'awaiting_human_selection'
    elif reviewed['verdict'] == 'no_findings':
        result['status'] = 'reviewed_no_findings'
    else:
        result['status'] = 'review_inconclusive'
    pp.save(job / 'pipeline.json', result)
    return result


def cli(argv=None):
    parser = argparse.ArgumentParser(description='Propose a task candidate FIRST, then review independently')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--task', help='Initial requirement, not a reviewer finding')
    mode.add_argument('--run', type=Path, help='Existing prepared task-proposal job')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--allow-file', action='append')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--confirm-paid', action='store_true',
                        help='Authorize at most TWO requests: proposal then review; no retries')
    args = parser.parse_args(argv)
    if args.task is not None and (not args.repo or not args.allow_file or not args.output):
        parser.error('--task requires --repo, --allow-file and --output')
    if args.task is not None and args.confirm_paid:
        parser.error('Prepare and inspect the scope first, then use --run --confirm-paid')
    if args.run and any((args.repo, args.allow_file, args.output)):
        parser.error('--run uses only the previously prepared scope')
    try:
        if args.task is not None:
            state = prepare_proposal(args.repo, args.task, args.allow_file, args.output)
            print(json.dumps({'status': state['status'], 'job': str(args.output.resolve()),
                              'model_requests': 0, 'next': 'initial proposal, then independent review'}))
            return 0
        state, snapshot, _ = pp.workspace_state(args.run)
        if state.get('job_kind') != 'task_proposal':
            raise ReviewError('This entry is for initial task proposals, not PR repair jobs')
        pp.source_version(state, snapshot)
        if not args.confirm_paid:
            print(json.dumps({'status': state['status'], 'model_requests': 0,
                              'existing_pipeline': (args.run / 'pipeline.json').exists()}))
            return 0
        if (args.run / 'pipeline.json').exists():
            raise ReviewError('Pipeline already attempted; no automatic retry')
        from novacore.config import load_config
        from novacore.pr_review import LiveReviewClient
        config = load_config()

        async def run():
            proposer, reviewer = LiveReviewClient(config), LiveReviewClient(config)
            try:
                return await run_proposal_review(args.run, proposer, reviewer)
            finally:
                await proposer.sdk.close()
                await reviewer.sdk.close()
        result = asyncio.run(run())
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return {'reviewed_no_findings': 0, 'awaiting_human_selection': 1}.get(result['status'], 2)
    except (ReviewError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        print('Proposal workflow unavailable. Check task scope, source version, output records and configuration. Existing edits and records are preserved; no publication occurred.')
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
