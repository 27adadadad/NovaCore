"""Prepare a GitHub Release candidate from an exact, successful CI artifact.

This script performs GitHub GETs only. It never creates tags or releases.
"""
from __future__ import annotations

import argparse
import base64
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tomllib
from urllib.parse import quote
import zipfile


def gh_json(route):
    p = subprocess.run(['gh', 'api', '--method', 'GET', route], capture_output=True, timeout=60)
    if p.returncode or len(p.stdout) > 4 * 1024 * 1024:
        raise ValueError('GitHub read unavailable or response too large; inspect gh access locally')
    return json.loads(p.stdout)


def require_sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('Invalid commit SHA')
    return value


def tag_commit(repo, tag):
    obj = gh_json(f'repos/{repo}/git/ref/tags/{quote(tag, safe="")}')['object']
    for _ in range(4):
        sha = require_sha(obj['sha'])
        if obj['type'] == 'commit':
            return sha
        if obj['type'] != 'tag':
            break
        obj = gh_json(f'repos/{repo}/git/tags/{sha}')['object']
    raise ValueError('Unsupported tag chain')


def prepare(repo, sha, tag, output, *, require_tag=True):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid repository')
    require_sha(sha)
    if not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', tag):
        raise ValueError('Use a final vMAJOR.MINOR.PATCH tag')
    if require_tag and tag_commit(repo, tag) != sha:
        raise ValueError('Tag no longer matches requested commit')
    # A successful PR merge-ref run is not release evidence. Require an exact
    # push run on the explicitly trusted product branch.
    runs = gh_json(f'repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&event=push&per_page=30')['workflow_runs']
    run = next((r for r in runs if r.get('head_sha') == sha and r.get('head_branch') == 'codex/pr-review'
                and r.get('head_repository', {}).get('full_name', '').casefold() == repo.casefold()
                and r.get('event') == 'push' and r.get('status') == 'completed'
                and r.get('conclusion') == 'success'), None)
    if run is None:
        raise ValueError('No successful exact-SHA push CI on codex/pr-review in bounded history; run CI first')
    run_id = int(run['id'])
    required = {f'{os} / Python {py}' for os in ('ubuntu-latest', 'windows-latest') for py in ('3.11', '3.13')}
    jobs = gh_json(f'repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100')
    if jobs['total_count'] > 100 or not required <= {j['name'] for j in jobs['jobs'] if j['conclusion'] == 'success'}:
        raise ValueError('Required CI matrix jobs have not all passed')
    compare = gh_json(f'repos/{repo}/compare/{sha}...codex%2Fpr-review')
    if compare.get('status') not in ('identical', 'ahead') or compare['merge_base_commit']['sha'] != sha:
        raise ValueError('Release commit is not on the trusted product branch')
    obj = gh_json(f'repos/{repo}/contents/pyproject.toml?ref={sha}')
    if obj.get('encoding') != 'base64' or obj.get('size', 65537) > 65536:
        raise ValueError('Version metadata unavailable')
    project = tomllib.loads(base64.b64decode(obj['content']).decode('utf-8'))['project']
    if project['name'] != 'novacore' or tag != 'v' + project['version']:
        raise ValueError('Tag must equal the exact commit project version')
    artifacts = gh_json(f'repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100')
    if artifacts['total_count'] > 100:
        raise ValueError('Too many artifacts')
    matches = [a for a in artifacts['artifacts'] if a['name'] == 'offline-ubuntu-latest-py3.13' and not a['expired']]
    if len(matches) != 1 or not 0 < matches[0]['size_in_bytes'] <= 32 * 1024 * 1024:
        raise ValueError('Expected one available bounded CI artifact; rerun CI if expired')
    artifact = matches[0]
    download = subprocess.run(['gh', 'api', '--method', 'GET',
        f'repos/{repo}/actions/artifacts/{int(artifact["id"])}/zip'], capture_output=True, timeout=60)
    if download.returncode or len(download.stdout) > 32 * 1024 * 1024:
        raise ValueError('CI artifact download unavailable or oversized')
    # Do not extract arbitrary ZIP paths. Read only the selected wheel bytes.
    with zipfile.ZipFile(io.BytesIO(download.stdout)) as z:
        wheels = [n for n in z.namelist() if n.startswith('dist/') and n.endswith('.whl')]
        if len(wheels) != 1:
            raise ValueError('CI artifact must contain exactly one wheel')
        name = PurePosixPath(wheels[0]).name
        if not re.fullmatch(r'novacore-[0-9]+\.[0-9]+\.[0-9]+-py3-none-any\.whl', name):
            raise ValueError('Unexpected distribution filename')
        info = z.getinfo(wheels[0])
        if info.file_size > 16 * 1024 * 1024:
            raise ValueError('Wheel exceeds size budget')
        wheel = z.read(wheels[0])
    with zipfile.ZipFile(io.BytesIO(wheel)) as z:
        metadata = [n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1 or z.getinfo(metadata[0]).file_size > 65536:
            raise ValueError('Invalid wheel metadata')
        headers = BytesParser().parsebytes(z.read(metadata[0]))
        if headers['Name'] != 'novacore' or headers['Version'] != project['version']:
            raise ValueError('Wheel metadata does not match source version')
    digest = hashlib.sha256(wheel).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / name).write_bytes(wheel)
    manifest = {'repository': repo, 'tag': tag, 'commit_sha': sha, 'ci_run_id': run_id,
                'ci_url': f'https://github.com/{repo}/actions/runs/{run_id}',
                'ci_artifact_id': artifact['id'], 'ci_artifact_digest': artifact.get('digest'),
                'version': project['version'], 'wheel': name, 'wheel_sha256': digest,
                'tag_verified': require_tag, 'publication': 'not_requested'}
    (output / 'release-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'notes.md').write_text(f'# NovaCore {tag}\n\nCommit: `{sha}`\n\n'
        f'CI: {manifest["ci_url"]}\n\nWheel SHA256: `{digest}`\n\n'
        'No model requests or deployment performed during release preparation.\n', encoding='utf-8')
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                   for p in sorted(output.iterdir()) if p.is_file())
    (output / 'SHA256SUMS').write_text(sums, encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--preview-without-tag', action='store_true',
                        help='Read-only preparation only; no tag required, never a publish authorization')
    args = parser.parse_args()
    try:
        prepare(args.repo, args.sha, args.tag, args.output, require_tag=not args.preview_without_tag)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile):
        raise SystemExit('Release preparation rejected: check exact tag/version, successful trusted CI, artifact availability and access. No release created.')
