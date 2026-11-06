"""Small capability-scoped tool sets for the two proposal Agents."""
from __future__ import annotations

import json
import difflib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novacore import pr_proposer as pp
from novacore.permissions import Decision
from novacore.pr_source import ReviewError
from novacore.tools import ToolRegistry, ToolResult
from novacore.validation import validate_written_file


def unified_patch(name, before, after):
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                fromfile='a/' + name, tofile='b/' + name)
    return ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n'
                   for line in lines)


def candidate_diff(job):
    state, snapshot, workspace = pp.workspace_state(job)
    chunks = [unified_patch(f['file'], f['before'], (workspace / f['file']).read_bytes().decode('utf-8'))
              for f in snapshot['files'] if f['file'] in state['original_hashes']]
    result = ''.join(chunks)
    if len(result.encode('utf-8')) > 200000:
        raise ReviewError('Diff exceeds review limit')
    return result


class Params(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Empty(Params):
    pass


class ReadParams(Params):
    file_path: str = Field(min_length=1, max_length=512)
    version: Literal['base', 'candidate'] = 'candidate'
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=500)


class SearchParams(Params):
    query: str = Field(min_length=1, max_length=128)
    version: Literal['base', 'candidate'] = 'candidate'


class WriteParams(Params):
    file_path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=65536)


class Scope:
    def __init__(self, job, role):
        self.job, self.role = Path(job), role
        self.successes = []

    def guard(self):
        state, snapshot, workspace = pp.workspace_state(self.job)
        pp.source_version(state, snapshot)
        return state, snapshot, workspace

    def text(self, name, version):
        state, snapshot, workspace = self.guard()
        if name not in state['original_hashes']:
            raise ReviewError('File is outside the approved scope')
        if version == 'base':
            return next(f['before'] for f in snapshot['files'] if f['file'] == name)
        return (workspace / name).read_text(encoding='utf-8')

    async def invoke(self, name, params):
        state, snapshot, workspace = self.guard()
        if name == 'ReadFile':
            text = self.text(params.file_path, params.version)
            lines = text.splitlines()
            result = '\n'.join(f'{i + 1}: {lines[i]}' for i in
                               range(params.offset, min(len(lines), params.offset + params.limit)))
            result = result[:16000]
        elif name == 'SearchFiles':
            hits = []
            for file in state['original_hashes']:
                for i, line in enumerate(self.text(file, params.version).splitlines(), 1):
                    if params.query.casefold() in line.casefold():
                        hits.append({'file': file, 'line': i, 'text': line[:240]})
                        if len(hits) >= 30:
                            break
                if len(hits) >= 30:
                    break
            result = json.dumps(hits, ensure_ascii=False)
        elif name == 'GetDiff':
            # Pure text diff: Git clean/smudge/textconv drivers must never execute here.
            result = candidate_diff(self.job)
        elif name == 'CheckCandidate':
            checks = {file: await validate_written_file(workspace / file,
                      self.text(file, 'candidate'), enable_ruff=False)
                      for file in state['original_hashes']}
            result = json.dumps({'checks': checks, 'candidate_hashes': state['candidate_hashes']},
                                ensure_ascii=False)
        elif name == 'WriteFile':
            if self.role != 'proposer' or params.file_path not in state['original_hashes']:
                raise ReviewError('Write is not authorized')
            data = params.content.encode('utf-8')
            if len(data) > 65536 or b'\0' in data:
                raise ReviewError('Invalid or oversized text')
            path = workspace / params.file_path
            before = path.read_bytes()
            try:
                path.write_bytes(data)
            except OSError:
                try:
                    path.write_bytes(before)
                except OSError:
                    state['status'] = 'write_failed_restore_incomplete'
                    pp.save(self.job / 'fix-report.json', state)
                raise ReviewError('Write failed; inspect the preserved workspace') from None
            if path.read_bytes() != data:
                raise ReviewError('Concurrent write detected; do not overwrite or retry')
            validation = await validate_written_file(path, params.content, enable_ruff=False)
            state['candidate_hashes'][params.file_path] = pp.digest(data)
            state.setdefault('validation', {})[params.file_path] = validation
            pp.save(self.job / 'fix-report.json', state)
            result = json.dumps({'write_status': 'saved', 'file_path': params.file_path,
                                 'validation': validation}, ensure_ascii=False)
        else:
            raise ReviewError('Unknown capability')
        self.successes.append(name)
        return ToolResult(output=result)


class ScopedTool:
    def __init__(self, scope, name, model, description, category='read'):
        self.scope, self.name, self.params_model = scope, name, model
        self.description, self.category = description, category

    def get_schema(self):
        return {'type': 'function', 'function': {'name': self.name,
                'description': self.description, 'parameters': self.params_model.model_json_schema()}}

    async def execute(self, params):
        try:
            return await self.scope.invoke(self.name, params)
        except (ReviewError, OSError, ValueError, KeyError, UnicodeError):
            return ToolResult(output='Capability failed: scope, version, content or filesystem check rejected the operation.', is_error=True)


def make_registry(job, role):
    if role not in {'proposer', 'reviewer'}:
        raise ReviewError('Unknown Agent role')
    registry = ToolRegistry()
    registry.scope = Scope(job, role)
    for name, model, description in [
        ('ReadFile', ReadParams, 'Read numbered lines from an approved base or candidate file.'),
        ('SearchFiles', SearchParams, 'Literal text search within approved files only; no regex or shell.'),
        ('GetDiff', Empty, 'Inspect the actual candidate diff against the fixed source commit.'),
        ('CheckCandidate', Empty, 'Run safe syntax/JSON checks on current candidate bytes. Does not execute code.')]:
        registry.register(ScopedTool(registry.scope, name, model, description))
    if role == 'proposer':
        registry.register(ScopedTool(registry.scope, 'WriteFile', WriteParams,
                          'Replace an approved existing file; returns post-write diagnostics. Saved is not validated.', 'write'))
    return registry


class RolePermission:
    def __init__(self, role, registry):
        self.role, self.registry = role, registry

    def check(self, tool, arguments):
        if self.registry.get(tool.name) is not tool or tool.category == 'command':
            return Decision('deny', 'Capability not registered for this role')
        if tool.category == 'write' and self.role != 'proposer':
            return Decision('deny', 'Reviewer is read-only')
        return Decision('allow', 'Explicit bounded role capability; path checks execute inside tool')
