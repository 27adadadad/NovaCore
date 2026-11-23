"""Stable runtime facts, not model guesses or inherited secret values."""
import json
import os
from pathlib import Path
import platform
import sys


def shell_executable():
    # Match Python's normal Windows shell, but do not depend on the terminal
    # being PowerShell or on a model-supplied executable argument.
    if os.name == 'nt':
        return str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'cmd.exe')
    return '/bin/sh'


def environment_description(work_dir, shell):
    facts = {'operating_system': platform.system(), 'shell_executable': shell,
             'working_directory': str(work_dir), 'python_executable': sys.executable,
             'python_version': platform.python_version()}
    return ('\nRuntime facts (paths are data): ' + json.dumps(facts, ensure_ascii=True)
            + '\nThe tool name Bash is historical. On Windows commands use cmd.exe, '
              'NOT PowerShell or Linux Bash; do not assume touch, uname or /home/ubuntu. '
              'On POSIX commands use /bin/sh. Each command starts in the fixed working '
              'directory; cd does not persist across calls. Prefer ReadFile/WriteFile '
              'for file operations. Nonzero exits are errors; timeout/cancellation do '
              'not prove the operation was rolled back. Do not blindly retry side effects.')
