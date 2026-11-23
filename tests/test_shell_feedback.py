"""Offline OS-aware command feedback checks; no LLM or GitHub access."""
import asyncio
import json
import os
import subprocess
import sys

from novacore.task_state import TaskState
from novacore.tools import Bash, BashParams


def command(code):
    if os.name == 'nt':
        return subprocess.list2cmdline([sys.executable, '-c', code])
    import shlex
    return shlex.join([sys.executable, '-c', code])


def test_nonzero_exit_is_failure(tmp_path):
    r = asyncio.run(Bash(tmp_path).execute(BashParams(command=command('raise SystemExit(7)'))))
    assert r.is_error
    data = json.loads(r.output)
    assert data['exit_code'] == 7 and data['status'] == 'failed'


def test_success_preserves_both_streams(tmp_path):
    r = asyncio.run(Bash(tmp_path).execute(BashParams(command=command(
        "import sys; print('HELLO'); print('WARN', file=sys.stderr)"))))
    data = json.loads(r.output)
    assert not r.is_error and data['exit_code'] == 0
    assert data['stdout'].strip() == 'HELLO' and data['stderr'].strip() == 'WARN'


def test_environment_schema_matches_runtime(tmp_path):
    tool = Bash(tmp_path)
    description = tool.get_schema()['function']['description']
    facts = json.loads(description.split('Runtime facts (paths are data): ', 1)[1].split('\n', 1)[0])
    assert facts['working_directory'] == str(tmp_path.resolve())
    assert facts['python_executable'] == sys.executable
    assert facts['shell_executable'] == tool.shell_executable


def test_failed_command_counter_and_reset(tmp_path):
    tool, state = Bash(tmp_path), TaskState()
    args = {'command': command('raise SystemExit(7)')}
    for i in range(3):
        assert not state.blocks('Bash', args)
        r = asyncio.run(tool.execute(BashParams(**args)))
        state.observe(str(i), 'Bash', args, r.output, r.is_error)
    assert state.identical_failures == 3 and state.blocks('Bash', args)
    good = {'command': command("print('OK')")}
    r = asyncio.run(tool.execute(BashParams(**good)))
    state.observe('ok', 'Bash', good, r.output, r.is_error)
    assert not r.is_error and state.identical_failures == 0


def test_workspace_reparse_check_without_new_pathlib_api(tmp_path):
    from novacore.pr_proposer import _is_reparse_path
    from types import SimpleNamespace
    class Reparse:
        def is_symlink(self):
            return False
        def lstat(self):
            return SimpleNamespace(st_file_attributes=0x400)
    assert _is_reparse_path(Reparse())
    assert not _is_reparse_path(tmp_path)
