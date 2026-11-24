"""Verify reference locations and exact excerpts, NOT semantic truth of claims."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novacore.tools import ToolResult


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    node_id: str = Field(max_length=16)
    commit_sha: str | None = Field(description='Exact commit_sha returned by ReadEvidence; null only when the node has no commit')
    field: Literal['content', 'patch', 'metadata'] = 'content'
    start_line: int = Field(default=1, ge=1)
    start_column: int = Field(default=0, ge=0)
    excerpt: str = Field(min_length=1, max_length=2000, description='Exact original excerpt at the specified line/column; do not paraphrase')


class CitationParams(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    artifact_id: str = Field(max_length=100)
    references: list[EvidenceReference] = Field(min_length=1, max_length=10)


class ValidateEvidenceCitations:
    name = 'ValidateEvidenceCitations'
    category = 'read'
    params_model = CitationParams
    description = ('Check current-session evidence citations: node, commit identity and exact excerpt '
                   'at field-relative line/Unicode column. No model or network request. '
                   'A matching reference does NOT prove the attached claim or business correctness.')

    def __init__(self, store):
        self.store = store

    def get_schema(self):
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description,
                                                'parameters': self.params_model.model_json_schema()}}

    async def execute(self, params):
        try:
            data = self.store.load(params.artifact_id)
            results = []
            for ref in params.references:
                answer = {'node_id': ref.node_id, 'matched': False}
                node = next((n for n in data['nodes'] if n['id'] == ref.node_id), None)
                if node is None:
                    answer['reason'] = 'unknown_node'
                elif node.get('commit_sha') != ref.commit_sha:
                    answer['reason'] = 'commit_mismatch'
                else:
                    if ref.field == 'metadata':
                        text = json.dumps({k: v for k, v in node['payload'].items() if k not in ('content', 'patch')},
                                          ensure_ascii=False, indent=2)
                    else:
                        text = node['payload'].get(ref.field)
                    if not isinstance(text, str):
                        answer['reason'] = 'field_unavailable'
                    else:
                        lines = text.splitlines(keepends=True)
                        index = ref.start_line - 1
                        if index >= len(lines) or ref.start_column >= len(lines[index]):
                            answer['reason'] = 'invalid_location'
                        else:
                            offset = sum(map(len, lines[:index])) + ref.start_column
                            if text[offset:offset + len(ref.excerpt)] != ref.excerpt:
                                answer['reason'] = 'excerpt_mismatch'
                            else:
                                answer.update(matched=True, reason='exact_text_match',
                                    source_url=node.get('source_url'), commit_sha=node.get('commit_sha'),
                                    field=ref.field, start_line=ref.start_line, start_column=ref.start_column,
                                    excerpt_sha256=hashlib.sha256(ref.excerpt.encode('utf-8')).hexdigest())
                results.append(answer)
            passed = all(item['matched'] for item in results)
            output = json.dumps({'status': 'matched' if passed else 'mismatch', 'references': results,
                'semantic_verification': False, 'artifact_acceptance': False,
                'coverage_status': data.get('coverage', {}).get('status', 'unknown'),
                'note': 'Text/identity checks only. Matching citations do not prove a conclusion; missing evidence remains unknown.'}, ensure_ascii=False)
            if len(output.encode('utf-8')) > 16384:
                raise ValueError('Citation response too large')
            return ToolResult(output=output, is_error=not passed)
        except Exception:
            return ToolResult(output=json.dumps({'status': 'unavailable', 'semantic_verification': False,
                'reason': 'Check registered session artifact and reference integrity; do not bypass with paths or Shell.'}), is_error=True)
