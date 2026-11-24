import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from novacore.evidence_reader import EvidenceStore, ReadEvidence, ReadEvidenceParams


def bundle(text='alpha\nbeta\ngamma\n', count=1):
    nodes = []
    for i in range(count):
        payload = {'path': f'file-{i}.py', 'content': text, 'patch': '+alpha\n'}
        nodes.append({'id': f'E{i+1}', 'kind': 'code', 'source_url': 'https://github.com/demo/repo/blob/'+'a'*40+'/app.py',
                      'repository': 'demo/repo', 'commit_sha': 'a'*40, 'captured_at': 'fixture',
                      'content_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                      'payload': payload, 'line_start': 1, 'line_end': len(text.splitlines())})
    return {'schema_version': 1, 'nodes': nodes, 'edges': [], 'coverage': {'status': 'partial', 'stale': False,
            'gaps': [{'scope': 'fixture', 'reason': 'no_ci'}]}, 'untrusted_evidence': True}


def saved(tmp_path, data=None):
    store = EvidenceStore(tmp_path / 'out', 'session_a')
    path = store.new_directory()
    path.mkdir(parents=True)
    (path / 'bundle.json').write_text(json.dumps(data or bundle(), ensure_ascii=False), encoding='utf-8')
    return store, path, store.register(path)


def invoke(store, **params):
    result = asyncio.run(ReadEvidence(store).execute(ReadEvidenceParams(**params)))
    return result, json.loads(result.output)


def test_catalog_excludes_body_and_paginates(tmp_path):
    store, _, ident = saved(tmp_path, bundle('PRIVATE_CONTENT', count=25))
    result, data = invoke(store, artifact_id=ident, action='list', limit=10)
    assert not result.is_error and len(data['nodes']) == 10 and data['next_offset'] == 10
    assert 'PRIVATE_CONTENT' not in result.output
    assert data['coverage']['status'] == 'partial'


def test_read_selected_node_field_with_provenance(tmp_path):
    store, path, ident = saved(tmp_path)
    result, data = invoke(store, artifact_id=ident, action='read', node_id='E1', field='content', start_line=2, max_lines=1)
    assert not result.is_error and data['content'] == 'beta\n'
    assert data['next_cursor'] == {'start_line': 3, 'start_column': 0}
    assert data['node']['commit_sha'] == 'a'*40
    assert data['untrusted_evidence'] and not data['eof']
    assert path.is_dir()


def test_long_unicode_line_reads_without_loss_or_stall(tmp_path):
    text = '中文😀\\"' * 8000 + '\nEND\n'
    store, path, ident = saved(tmp_path, bundle(text))
    original = (path / 'bundle.json').read_bytes()
    cursor, chunks = {}, []
    for _ in range(200):
        result, data = invoke(store, artifact_id=ident, action='read', node_id='E1', field='content', **cursor)
        assert not result.is_error and len(result.output.encode('utf-8')) <= 16384
        chunks.append(data['content'])
        if data['eof']:
            break
        assert data['next_cursor'] != cursor
        cursor = data['next_cursor']
    else:
        pytest.fail('Reader failed to terminate')
    assert ''.join(chunks) == text
    assert (path / 'bundle.json').read_bytes() == original


@pytest.mark.parametrize('ident', ['../bundle.json', 'C:\\secret', '/etc/passwd', 'artifact-'+'0'*32])
def test_unknown_or_unsafe_ids_never_read_paths(tmp_path, ident):
    store, _, _ = saved(tmp_path)
    r, data = invoke(store, artifact_id=ident, action='list')
    assert r.is_error and data['status'] == 'unavailable'


def test_cross_session_denied_and_same_session_restored(tmp_path):
    store, _, ident = saved(tmp_path)
    other = EvidenceStore(tmp_path / 'out', 'session_b')
    assert invoke(other, artifact_id=ident, action='list')[0].is_error
    reopened = EvidenceStore(tmp_path / 'out', 'session_a')
    assert not invoke(reopened, artifact_id=ident, action='list')[0].is_error


def test_modified_bundle_rejected(tmp_path):
    store, path, ident = saved(tmp_path)
    (path / 'bundle.json').write_text('{}', encoding='utf-8')
    assert invoke(store, artifact_id=ident, action='list')[0].is_error


def test_node_field_range_and_extra_path_rejected(tmp_path):
    store, _, ident = saved(tmp_path)
    for args in [{'node_id': 'E999'}, {'node_id': 'E1', 'start_line': 999}, {'node_id': 'E1', 'start_column': 999}]:
        assert invoke(store, artifact_id=ident, action='read', **args)[0].is_error
    with pytest.raises(ValueError):
        ReadEvidenceParams(artifact_id=ident, file_path='secret')


def test_collector_reader_share_store_offline(tmp_path):
    from test_dev_evidence import API, URL
    from novacore.dev_evidence import CollectDevEvidence, EvidenceParams
    store = EvidenceStore(tmp_path / 'out', 'session_a')
    tool = CollectDevEvidence(tmp_path / 'repo', store=store, api_factory=API)
    result = asyncio.run(tool.execute(EvidenceParams(url=URL)))
    assert not result.is_error
    info = json.loads(result.output)
    r, catalog = invoke(store, artifact_id=info['artifact_id'], action='list')
    assert not r.is_error and catalog['nodes']
    r, data = invoke(store, artifact_id=info['artifact_id'], action='read', node_id='E1', field='metadata')
    assert not r.is_error and 'change' in data['content']


def test_symlink_bundle_denied(tmp_path):
    store, path, ident = saved(tmp_path)
    target = tmp_path / 'outside.json'
    target.write_bytes((path / 'bundle.json').read_bytes())
    (path / 'bundle.json').unlink()
    try:
        (path / 'bundle.json').symlink_to(target)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    assert invoke(store, artifact_id=ident, action='list')[0].is_error


def test_registry_failure_does_not_grant_unknown_access(tmp_path):
    store, _, ident = saved(tmp_path)
    (store.session_dir / 'registry.json').write_text('{broken', encoding='utf-8')
    reopened = EvidenceStore(tmp_path / 'out', 'session_a')
    assert invoke(reopened, artifact_id=ident, action='list')[0].is_error


def test_patch_and_metadata_are_separate_views(tmp_path):
    store, _, ident = saved(tmp_path, bundle('BODY_NOT_IN_METADATA'))
    r, value = invoke(store, artifact_id=ident, action='read', node_id='E1', field='patch')
    assert not r.is_error and value['content'] == '+alpha\n'
    r, value = invoke(store, artifact_id=ident, action='read', node_id='E1', field='metadata')
    assert not r.is_error and 'BODY_NOT_IN_METADATA' not in r.output


def test_unregistered_or_oversized_bundle_not_accepted(tmp_path):
    from novacore.evidence_reader import MAX_BUNDLE_BYTES
    store = EvidenceStore(tmp_path / 'out', 'session_a')
    wrong = tmp_path / 'other'
    wrong.mkdir()
    (wrong / 'bundle.json').write_text(json.dumps(bundle()))
    with pytest.raises(ValueError):
        store.register(wrong)
    target = store.new_directory()
    target.mkdir(parents=True)
    (target / 'bundle.json').write_bytes(b' ' * (MAX_BUNDLE_BYTES + 1))
    with pytest.raises(ValueError):
        store.register(target)


def test_reparse_marked_paths_denied_without_link_privilege(tmp_path, monkeypatch):
    store, path, ident = saved(tmp_path)
    original = Path.lstat
    from types import SimpleNamespace
    def fake_lstat(self, *args, **kwargs):
        if self == path:
            return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', fake_lstat)
    assert invoke(store, artifact_id=ident, action='list')[0].is_error


def test_atomic_registry_preserves_existing_entries_on_replace_error(tmp_path, monkeypatch):
    store, _, ident = saved(tmp_path)
    new = store.new_directory()
    new.mkdir()
    (new / 'bundle.json').write_text(json.dumps(bundle()), encoding='utf-8')
    def failed(*args):
        raise OSError('Disk unavailable')
    monkeypatch.setattr('novacore.evidence_reader.os.replace', failed)
    with pytest.raises(OSError):
        store.register(new)
    assert not invoke(store, artifact_id=ident, action='list')[0].is_error
    assert invoke(store, artifact_id=new.name, action='list')[0].is_error


def test_real_agent_collect_list_read_without_shell(tmp_path):
    from novacore.agent import Agent
    from novacore.client import ClientResponse, ToolCall
    from novacore.dev_evidence import CollectDevEvidence
    from novacore.tools import ToolRegistry
    from test_dev_evidence import API, URL
    store = EvidenceStore(tmp_path / 'out', 'session_a')
    registry = ToolRegistry()
    registry.register(CollectDevEvidence(tmp_path / 'repo', store=store, api_factory=API))
    registry.register(ReadEvidence(store))
    class Client:
        count = 0
        async def complete(self, messages, tools):
            assert {t['function']['name'] for t in tools} == {'CollectDevEvidence', 'ReadEvidence'}
            self.count += 1
            if self.count == 1:
                return ClientResponse(tool_calls=[ToolCall('collect', 'CollectDevEvidence', {'url': URL})])
            result = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
            if self.count == 2:
                self.ident = result['artifact_id']
                return ClientResponse(tool_calls=[ToolCall('catalog', 'ReadEvidence', {'artifact_id': self.ident})])
            if self.count == 3:
                assert result['nodes'][0]['id'] == 'E1'
                return ClientResponse(tool_calls=[ToolCall('read', 'ReadEvidence', {
                    'artifact_id': self.ident, 'action': 'read', 'node_id': 'E1', 'field': 'metadata'})])
            assert result['node']['id'] == 'E1' and 'change' in result['content']
            return ClientResponse(text='Read selected evidence only; coverage remains partial.')
    client = Client()
    answer = asyncio.run(Agent(client=client, registry=registry, context_window=128000).run_to_completion('Collect and inspect evidence'))
    assert client.count == 4 and 'partial' in answer
    assert registry.get('Bash') is None and registry.get('ReadFile') is None
