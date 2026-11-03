"""Bounded, read-only GitHub PR collection. No repository code is executed."""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote


class ReviewError(RuntimeError):
    """Safe to display: never include transport stderr or credentials."""


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/"
        r"([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})/pull/([1-9][0-9]{0,9})"
        r"(?:/(?:files|commits))?/?", url,
    )
    if not match or match[2] in {'.', '..'}:
        raise ReviewError('Expected https://github.com/OWNER/REPO/pull/NUMBER')
    return match[1], match[2], int(match[3])


class GitHubGET:
    """Use existing gh authentication without reading credential values."""

    def __init__(self):
        self.executable = shutil.which('gh')
        if not self.executable:
            raise ReviewError('GitHub CLI is missing; install gh and sign in locally.')
        self.deadline = time.monotonic() + 120

    def get(self, route: str):
        if not route.startswith('/repos/') or any(c in route for c in '\r\n\\'):
            raise ReviewError('Rejected GitHub API route')
        timeout = min(30, self.deadline - time.monotonic())
        if timeout <= 0:
            raise ReviewError('GitHub collection time budget exceeded')
        # Bounded files prevent unbounded communicate() allocation. Never print stderr.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(
                    [self.executable, 'api', '--hostname', 'github.com', '--method',
                     'GET', '-H', 'Accept: application/vnd.github+json', route],
                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, shell=False,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            except OSError:
                raise ReviewError('Cannot start GitHub CLI') from None
            end = time.monotonic() + timeout
            try:
                while proc.poll() is None:
                    if time.monotonic() > end:
                        raise ReviewError('GitHub request timed out')
                    if out.tell() > 2 * 1024 * 1024 or err.tell() > 64 * 1024:
                        raise ReviewError('GitHub response exceeded the size limit')
                    time.sleep(.02)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
            if proc.returncode:
                raise ReviewError('GitHub GET failed; check gh login, PR access and rate limits.')
            out.seek(0)
            raw = out.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ReviewError('GitHub response exceeded the size limit')
            try:
                return json.loads(raw)
            except (ValueError, UnicodeError):
                raise ReviewError('GitHub returned invalid JSON') from None


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ReviewError('Invalid commit identity')
    return value


def _repo(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', value, re.ASCII):
        raise ReviewError('Unavailable repository identity')
    return value


def _path_reason(name):
    if not isinstance(name, str) or not name or len(name) > 512:
        return 'unsafe_path'
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(ord(c) < 32 for c in name) or '\\' in name:
        return 'unsafe_path'
    lowered = name.lower()
    if any(part.startswith('.env') or part in {'.ssh', '.aws', '.azure', '.gnupg'}
           for part in path.parts) or re.search(
               r'(credential|secret|token|id_rsa|id_ed25519)|\.(pem|key|p12|pfx)$', lowered):
        return 'sensitive_path'
    if any(part in {'node_modules', 'dist', 'build', 'vendor', '__pycache__'} for part in path.parts):
        return 'generated_path'
    if path.name in {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'uv.lock', 'poetry.lock'}:
        return 'lockfile'
    return None


def collect_pr(url: str, api=None, *, max_files=30, max_bytes=200 * 1024) -> dict:
    owner, repo, number = parse_pr_url(url)
    api = api if api is not None else GitHubGET()
    route = f'/repos/{owner}/{repo}/pulls/{number}'
    try:
        meta = api.get(route)
        base, head = _sha(meta['base']['sha']), _sha(meta['head']['sha'])
        base_repo = _repo(meta['base']['repo']['full_name'])
        head_repo = _repo(meta['head']['repo']['full_name'])
        total = meta['changed_files']
        if type(total) is not int or not 0 <= total <= 100000:
            raise ReviewError('Invalid changed-file count')
        merge = api.get(f'/repos/{base_repo}/compare/{base}...{head}')
        merge_base = _sha(merge['merge_base_commit']['sha'])
    except (KeyError, TypeError):
        raise ReviewError('GitHub metadata is incomplete') from None
    skips = []
    files = []
    # Metadata shares the context budget; hidden instructions remain untrusted data.
    metadata = {k: str(meta.get(k) or '')[:8000] for k in ('title', 'body')}
    used = len(json.dumps(metadata).encode('utf-8'))
    listed = []
    for page in range(1, (max_files // 30) + 2):
        batch = api.get(f'{route}/files?per_page=30&page={page}')
        if not isinstance(batch, list):
            raise ReviewError('GitHub file list is invalid')
        listed.extend(batch)
        if len(batch) < 30 or len(listed) >= min(total, max_files + 1):
            break
    if len(listed) != total or total > max_files:
        skips.append({'file': None, 'reason': 'file_list_limit_or_incomplete'})

    def content(repository, name, sha):
        obj = api.get(f'/repos/{repository}/contents/{quote(name, safe="/")}?ref={sha}')
        if not isinstance(obj, dict) or obj.get('type') != 'file':
            raise ReviewError('Unsupported content type')
        if type(obj.get('size')) is not int or not 0 <= obj['size'] <= 65536:
            raise ReviewError('File size limit')
        if obj.get('encoding') != 'base64':
            raise ReviewError('Unsupported file encoding')
        try:
            raw = base64.b64decode(''.join(obj['content'].split()), validate=True)
            if len(raw) > 65536 or b'\0' in raw:
                raise ReviewError('Binary or oversized content')
            return raw.decode('utf-8')
        except (KeyError, ValueError, UnicodeError, binascii.Error):
            raise ReviewError('File is not supported UTF-8 text') from None

    seen = set()
    for item in listed[:max_files]:
        if not isinstance(item, dict):
            raise ReviewError('Invalid file metadata')
        name = item.get('filename')
        previous = item.get('previous_filename', name)
        reason = _path_reason(name) or _path_reason(previous)
        if name in seen:
            reason = 'duplicate_path'
        seen.add(name)
        patch = item.get('patch')
        if reason is None and (not isinstance(patch, str) or not patch):
            reason = 'missing_patch_or_binary'
        if reason is None and len(patch.encode('utf-8')) > 65536:
            reason = 'patch_size_limit'
        if reason is not None:
            skips.append({'file': name, 'reason': reason})
            continue
        if used >= max_bytes:
            skips.append({'file': name, 'reason': 'context_budget'})
            continue
        status = item.get('status')
        if status not in {'added', 'modified', 'removed', 'renamed', 'copied', 'changed'}:
            skips.append({'file': name, 'reason': 'unsupported_status'})
            continue
        try:
            before = '' if status == 'added' else content(base_repo, previous, merge_base)
            after = '' if status == 'removed' else content(head_repo, name, head)
        except ReviewError:
            skips.append({'file': name, 'reason': 'content_unavailable_or_unsupported'})
            continue
        entry = {'file': name, 'previous_file': previous, 'status': status,
                 'patch': patch, 'before': before, 'after': after}
        size = len(json.dumps(entry, ensure_ascii=False).encode('utf-8'))
        if used + size > max_bytes:
            skips.append({'file': name, 'reason': 'context_budget'})
            continue
        used += size
        files.append(entry)
    final = api.get(route)
    try:
        stale = final['base']['sha'] != base or final['head']['sha'] != head
    except (KeyError, TypeError):
        raise ReviewError('Cannot confirm final PR version') from None
    if stale:
        skips.append({'file': None, 'reason': 'pr_updated_during_collection'})
    return {'pr_url': f'https://github.com/{owner}/{repo}/pull/{number}',
            'base_sha': base, 'head_sha': head, 'merge_base_sha': merge_base,
            'metadata': metadata, 'files': files,
            'coverage': {'status': 'partial' if skips else 'complete', 'stale': stale,
                         'total_files': total, 'included_files': len(files),
                         'material_bytes': used, 'skipped': skips,
                         'scope': 'selected changed files only; no automatic related-code retrieval'}}
