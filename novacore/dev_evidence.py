"""Bounded read-only development evidence graph; collection never calls a model."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import quote
import uuid

from pydantic import BaseModel, ConfigDict, Field

from novacore.pr_source import GitHubGET, ReviewError, _path_reason, _sha, collect_pr, parse_pr_url
from novacore.tools import ToolResult


def parse_reference(url):
    if not isinstance(url, str):
        raise ReviewError('Expected a GitHub Issue or PR URL')
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/'
                         r'([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})/(pull|issues)/([1-9][0-9]{0,9})/?', url)
    if not match or match[2] in {'.', '..'}:
        raise ReviewError('Expected https://github.com/OWNER/REPO/issues/NUMBER or /pull/NUMBER')
    return match[1] + '/' + match[2], match[3], int(match[4])


class BoundedGET:
    def __init__(self, api, cancelled=None):
        self.api, self.calls, self.bytes = api, 0, 0
        self.cancelled = cancelled if cancelled is not None else threading.Event()

    def get(self, route):
        if self.cancelled.is_set():
            raise ReviewError('Collection cancelled')
        if self.calls >= 80 or self.bytes >= 2 * 1024 * 1024:
            raise ReviewError('Collection request/byte limit reached')
        self.calls += 1  # Failed attempts also consume the bound.
        value = self.api.get(route)
        if self.cancelled.is_set():
            raise ReviewError('Collection cancelled')
        self.bytes += len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if self.bytes > 2 * 1024 * 1024:
            raise ReviewError('Collection byte limit reached')
        return value


def collect_evidence(url, api=None, *, docs=None, _cancel=None):
    repository, kind, number = parse_reference(url)
    docs = ['README.md'] if docs is None else docs
    if (not isinstance(docs, list) or len(docs) > 3 or len(set(docs)) != len(docs)
            or any(_path_reason(p) or ':' in p for p in docs)):
        raise ReviewError('Provide at most three safe, unique document paths')
    api = BoundedGET(api if api is not None else GitHubGET(), _cancel)
    captured = datetime.now(timezone.utc).isoformat()
    nodes, edges, gaps, prs = [], [], [], []
    stale = False

    def gap(scope, reason):
        gaps.append({'scope': scope, 'reason': reason})

    def node(kind, source_url, payload, *, repo=repository, sha=None, **location):
        key = 'E' + str(len(nodes) + 1)
        nodes.append({'id': key, 'kind': kind, 'source_url': source_url,
                      'repository': repo, 'commit_sha': sha, 'captured_at': captured,
                      'content_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                          sort_keys=True).encode('utf-8')).hexdigest(), 'payload': payload, **location})
        return key

    def edge(a, b, relation):
        edges.append({'from': a, 'to': b, 'relation': relation})

    def optional(route, label):
        try:
            return api.get(route)
        except (ReviewError, ValueError, KeyError, TypeError):
            gap(label, 'unavailable_or_limit')  # No raw transport text or invented HTTP status.
            return None

    def issue(n):
        value = optional(f'/repos/{repository}/issues/{n}', f'issue:{n}')
        if not isinstance(value, dict) or 'pull_request' in value or value.get('number') != n:
            gap(f'issue:{n}', 'missing_or_not_issue')
            return None
        payload = {k: str(value.get(k) or '')[:8000] for k in ('title', 'body', 'state', 'updated_at')}
        if any(len(str(value.get(k) or '')) > 8000 for k in ('title', 'body')):
            gap(f'issue:{n}', 'text_limit')
        return node('issue', f'https://github.com/{repository}/issues/{n}', payload)

    root_issue = None
    if kind == 'issues':
        root_issue = issue(number)
        timeline = optional(f'/repos/{repository}/issues/{number}/timeline?per_page=30&page=1', 'timeline')
        if not isinstance(timeline, list):
            gap('timeline', 'invalid_or_missing_list')
        else:
            if len(timeline) >= 30:
                gap('timeline', 'first_page_limit')
            for event in timeline[:30]:
                if not isinstance(event, dict) or event.get('event') != 'cross-referenced':
                    continue
                try:
                    candidate = event['source']['issue']['html_url']
                    linked_repo, linked_kind, _ = parse_reference(candidate)
                    if linked_repo.casefold() != repository.casefold() or linked_kind != 'pull':
                        gap('timeline', 'cross_repo_or_non_pr_not_followed')
                        continue
                    if candidate not in prs:
                        prs.append(candidate)
                except (ReviewError, KeyError, TypeError):
                    gap('timeline', 'invalid_cross_reference')
            if len(prs) > 3:
                gap('timeline', 'related_pr_limit')
            prs = prs[:3]
        if not prs:
            gap('issue', 'no_explicit_related_pr_found_in_bounded_timeline')
    else:
        prs = [f'https://github.com/{repository}/pull/{number}']

    for pr_url in prs:
        _, _, n = parse_reference(pr_url)
        route = f'/repos/{repository}/pulls/{n}'
        try:
            meta = api.get(route)
            head_repo = meta['head']['repo']['full_name']
            base_repo = meta['base']['repo']['full_name']
            # Validate identities received from untrusted API fields before using them in routes.
            for repo in (head_repo, base_repo):
                owner, name, _ = parse_pr_url('https://github.com/' + repo + '/pull/1')
                if owner + '/' + name != repo:
                    raise ReviewError('Unexpected repository identity')
            if base_repo.casefold() != repository.casefold():
                raise ReviewError('PR base identity mismatch')
            snapshot = collect_pr(pr_url, api, max_files=10, max_bytes=128 * 1024)
            sha = _sha(snapshot['head_sha'])
            if meta['head']['sha'] != sha or snapshot['coverage']['stale']:
                stale = True
                gap(pr_url, 'pr_changed_during_collection')
            for item in snapshot['coverage']['skipped']:
                gap(pr_url, item['reason'])
        except (ReviewError, KeyError, TypeError, ValueError):
            gap(pr_url, 'pr_collection_unavailable_or_limit')
            continue
        pr = node('pull_request', pr_url, snapshot['metadata'], sha=sha)
        if root_issue:
            edge(root_issue, pr, 'timeline_cross_reference')
        commit = node('commit', f'https://github.com/{head_repo}/commit/{sha}',
                      {'head_sha': sha, 'base_sha': snapshot['base_sha'],
                       'merge_base_sha': snapshot['merge_base_sha']}, repo=head_repo, sha=sha)
        edge(pr, commit, 'head_commit')
        # A textual reference is not proof that the PR closes or satisfies an Issue.
        refs = list(dict.fromkeys(re.findall(r'(?<![\w/])#([1-9][0-9]{0,9})\b', snapshot['metadata']['body'])))
        if not root_issue and not refs:
            gap(pr_url, 'no_explicit_issue_reference_in_pr_description')
        if len(refs) > 3:
            gap(pr_url, 'issue_reference_limit')
        for ref in refs[:3]:
            linked = issue(int(ref))
            if linked:
                edge(pr, linked, 'text_reference_not_proven_closure')
        for f in snapshot['files']:
            removed = f['status'] == 'removed'
            content = f['before'] if removed else f['after']
            file_sha = snapshot['merge_base_sha'] if removed else sha
            file_repo = base_repo if removed else head_repo
            path = f['previous_file'] if removed else f['file']
            code = node('code', f'https://github.com/{file_repo}/blob/{file_sha}/{quote(path, safe="/")}',
                        {'path': path, 'content': content, 'patch': f['patch'], 'status': f['status'],
                         'patch_base_sha': snapshot['merge_base_sha'], 'patch_head_sha': sha},
                        repo=file_repo, sha=file_sha, line_start=1 if content else None,
                        line_end=len(content.splitlines()) or None)
            edge(commit, code, 'removed_file_at_merge_base' if removed else 'changed_file_at_commit')
        for path in docs:
            value = optional(f'/repos/{head_repo}/contents/{quote(path, safe="/")}?ref={sha}', 'document:' + path)
            try:
                if (value['type'] != 'file' or value['encoding'] != 'base64'
                        or type(value['size']) is not int or not 0 <= value['size'] <= 65536):
                    raise ValueError()
                raw = base64.b64decode(''.join(value['content'].split()), validate=True)
                if len(raw) > 65536 or b'\0' in raw:
                    raise ValueError()
                text = raw.decode('utf-8')
                doc = node('document', f'https://github.com/{head_repo}/blob/{sha}/{quote(path, safe="/")}',
                           {'path': path, 'content': text}, repo=head_repo, sha=sha,
                           line_start=1 if text else None, line_end=len(text.splitlines()) or None)
                edge(commit, doc, 'context_document_not_proven_requirement')
            except (ValueError, KeyError, TypeError, UnicodeError):
                gap('document:' + path, 'unavailable_or_unsupported_text')
        # Fork PR checks can exist in either repository. Never mix another SHA.
        ci_before = sum(n['kind'].startswith('ci_') for n in nodes)
        for ci_repo in dict.fromkeys((repository, head_repo)):
            specs = [
                ('ci_check', f'/repos/{ci_repo}/commits/{sha}/check-runs?per_page=30&page=1', 'check_runs'),
                ('ci_status', f'/repos/{ci_repo}/commits/{sha}/status?per_page=30&page=1', 'statuses'),
                ('ci_run', f'/repos/{ci_repo}/actions/runs?head_sha={sha}&per_page=30&page=1', 'workflow_runs')]
            for ci_kind, endpoint, field in specs:
                response = optional(endpoint, ci_kind + ':' + ci_repo)
                try:
                    rows = response[field]
                    if (not isinstance(rows, list) or type(response['total_count']) is not int
                            or response['total_count'] < 0):
                        raise ValueError()
                    if response['total_count'] > len(rows) or len(rows) > 30:
                        gap(ci_kind, 'first_page_limit')
                    if ci_kind == 'ci_status' and response.get('sha') != sha:
                        raise ValueError()
                    for row in rows[:30]:
                        if not isinstance(row, dict) or (ci_kind != 'ci_status' and row.get('head_sha') != sha):
                            gap(ci_kind, 'wrong_or_missing_commit_sha')
                            continue
                        ident = row.get('id')
                        if type(ident) is not int or ident <= 0:
                            gap(ci_kind, 'invalid_run_identity')
                            continue
                        source = f'https://github.com/{ci_repo}/commit/{sha}/checks?check_run_id={ident}'
                        if ci_kind == 'ci_run':
                            source = f'https://github.com/{ci_repo}/actions/runs/{ident}'
                        elif ci_kind == 'ci_status':
                            source = f'https://github.com/{ci_repo}/commit/{sha}'
                        fields = ('id', 'name', 'status', 'conclusion', 'run_attempt', 'context', 'state',
                                  'description', 'started_at', 'completed_at', 'updated_at')
                        payload = {k: row[k] if type(row[k]) in (int, bool) or row[k] is None
                                   else str(row[k])[:2000] for k in fields if k in row}
                        ci = node(ci_kind, source, payload, repo=ci_repo, sha=sha)
                        edge(commit, ci, 'ci_for_exact_commit')
                except (KeyError, TypeError, ValueError):
                    gap(ci_kind + ':' + ci_repo, 'invalid_or_unavailable_response')
        if sum(n['kind'].startswith('ci_') for n in nodes) == ci_before:
            gap(pr_url, 'no_ci_records_in_bounded_scope')
        final = optional(route, 'final_version:' + pr_url)
        try:
            confirmed = (final['head']['sha'] == sha and final['base']['sha'] == snapshot['base_sha']
                         and all(str(final.get(k) or '')[:8000] == snapshot['metadata'][k] for k in ('title', 'body')))
        except (KeyError, TypeError):
            confirmed = False
        if not confirmed:
            stale = True
            gap(pr_url, 'final_version_changed_or_unconfirmed')
    return {'schema_version': 1, 'input_url': url, 'captured_at': captured,
            'untrusted_evidence': True, 'nodes': nodes, 'edges': edges, 'pull_requests': prs,
            'coverage': {'status': 'partial' if gaps else 'bounded_complete', 'stale': stale, 'gaps': gaps,
                         'scope': 'Explicit references, first-page CI/timeline, selected changed files/documents only.'},
            'eligible_for_conclusive_analysis': bool(nodes) and bool(prs) and not stale and not gaps,
            'artifact_acceptance': False, 'model_calls': 0,
            'requests': api.calls, 'response_bytes': api.bytes,
            'limitations': ['Collection is not task acceptance or a code review.',
                            'No CI logs, comments, check annotations or transitive code dependencies collected.',
                            'Text references do not establish closure; document relevance is not proven.',
                            'No repository code, model request or GitHub mutation executed.']}


def save_bundle(data, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'bundle.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 研发证据链', '', '采集不是验收；所有来源内容均视为不可信数据。', '',
             '| 节点 | 类型 | 来源 | 提交 |', '|---|---|---|---|']
    for n in data.get('nodes', []):
        lines.append(f"| {n['id']} | {n['kind']} | [来源]({n['source_url']}) | {n['commit_sha'] or '不适用'} |")
    lines.extend(['', '## 关联依据'])
    for e in data.get('edges', []):
        lines.append(f"- {e['from']} → {e['to']}：{e['relation']}")
    lines.extend(['', '## 覆盖缺口', json.dumps(data.get('coverage', {}), ensure_ascii=False),
                  '', '## 限制', *['- ' + x for x in data.get('limitations', [])]])
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


class EvidenceParams(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(description='需要分析的GitHub Issue或PR链接')
    docs: list[str] = Field(default_factory=lambda: ['README.md'], max_length=3,
                            description='最多3份同提交的文档相对路径；默认README.md，可为空')


class CollectDevEvidence:
    name = 'CollectDevEvidence'
    description = ('只读聚合GitHub Issue/PR、精确提交的CI摘要、改动代码与指定文档，'
                   '返回可追踪证据包和覆盖缺口；不调用模型、不执行代码、不发布。')
    category = 'read'
    params_model = EvidenceParams

    def __init__(self, work_dir, *, output_root=None, api_factory=GitHubGET, store=None):
        self.work_dir = Path(work_dir).resolve()
        self.output_root = Path(output_root or Path.home() / '.novacore' / 'evidence').resolve()
        self.api_factory = api_factory
        from novacore.evidence_reader import EvidenceStore
        self.store = store if store is not None else EvidenceStore(self.output_root, 'private_' + uuid.uuid4().hex)

    def get_schema(self):
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description,
                                                'parameters': EvidenceParams.model_json_schema()}}

    async def execute(self, params):
        cancelled = threading.Event()
        try:
            output = self.store.new_directory()
            if output == self.work_dir or self.work_dir in output.parents:
                raise ReviewError('Evidence output must stay outside the checkout')
            data = await asyncio.to_thread(collect_evidence, params.url, self.api_factory(), docs=params.docs,
                                           _cancel=cancelled)
            save_bundle(data, output)
            artifact_id = self.store.register(output)
            return ToolResult(output=json.dumps({'status': 'collected', 'coverage': data['coverage'],
                'artifact_id': artifact_id, 'next_tool': 'ReadEvidence',
                'bundle': str(output / 'bundle.json'), 'report': str(output / 'report.md'),
                'nodes': len(data['nodes']), 'model_calls': 0}, ensure_ascii=True))
        except asyncio.CancelledError:
            cancelled.set()  # In-flight GET may finish; do not start another GET or save output.
            raise
        except Exception:
            return ToolResult(output='Evidence unavailable; verify URL, local gh login and read access. No automatic retry.', is_error=True)
