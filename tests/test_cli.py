from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_python(arguments, tmp_path):
    # Only carry non-sensitive OS settings; never inherit model credentials.
    env = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR")
        if name in os.environ
    }
    env.update(TMP=str(tmp_path), TEMP=str(tmp_path), PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["-m", "novacore", "--help"],
        ["-c", "from novacore.__main__ import cli; cli()", "--help"],
    ],
    ids=["module", "console-entry-function"],
)
def test_help_starts_without_credentials(arguments, tmp_path):
    result = _run_python(arguments, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "--prompt" in result.stdout
    assert "--stream" in result.stdout


def test_stream_requires_prompt_before_loading_credentials(tmp_path):
    result = _run_python(["-m", "novacore", "--stream"], tmp_path)

    assert result.returncode == 2, result.stderr
    assert "--stream requires --prompt" in result.stderr


def test_missing_credentials_exits_with_clear_configuration_error(tmp_path):
    result = _run_python(["-m", "novacore", "-p", "hello"], tmp_path)

    assert result.returncode == 1
    assert "DASHSCOPE_API_KEY is required" in result.stderr
    assert "Traceback" not in result.stderr


def test_offline_example_runs_real_tool_and_restores_session(tmp_path):
    result = _run_python(["-m", "novacore.examples.offline_smoke"], tmp_path)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "offline-fake-client"
    assert report["model_calls"] == 2
    assert "NovaCore offline sample" in report["tool_output"]
    assert report["session_restored"] is True
    assert report["call_result_pair_preserved"] is True
    assert report["tool_name"] == "ReadFile"
