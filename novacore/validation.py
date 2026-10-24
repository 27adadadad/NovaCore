"""Bounded, non-executing checks for files written by the agent."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 512_000
MAX_CHECKER_OUTPUT = 64_000
MAX_DIAGNOSTICS = 20
CHECKER_TIMEOUT = 5.0


def _check(checker: str, status: str, diagnostics: list | None = None,
           reason: str = "") -> dict[str, Any]:
    return {"checker": checker, "status": status,
            "diagnostics": diagnostics or [], "reason": reason}


def _diagnostic(code: str, message: str, line: int = 1, column: int = 1) -> dict:
    return {"code": code, "message": message[:500],
            "line": max(1, line), "column": max(1, column)}


class _OutputLimit(Exception):
    pass


async def _read_bounded(stream: asyncio.StreamReader) -> bytes:
    data = bytearray()
    while True:
        chunk = await stream.read(min(8192, MAX_CHECKER_OUTPUT + 1 - len(data)))
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > MAX_CHECKER_OUTPUT:
            raise _OutputLimit


async def _ruff(path: Path, content: str) -> dict:
    # No shell, project config, plugins, installs, fixes or inherited credentials.
    env = {key: os.environ[key] for key in (
        "SYSTEMROOT", "SystemRoot", "WINDIR", "PATH", "TEMP", "TMP",
    ) if key in os.environ}
    process = None
    tasks: list[asyncio.Task] = []
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", "ruff", "check", "--isolated",
            "--select", "F821,F822,F823", "--output-format", "json",
            "--no-cache", "--stdin-filename", str(path), "-",
            cwd=path.parent, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def send() -> None:
            process.stdin.write(content.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

        tasks = [asyncio.create_task(send()),
                 asyncio.create_task(_read_bounded(process.stdout)),
                 asyncio.create_task(_read_bounded(process.stderr)),
                 asyncio.create_task(process.wait())]
        _, stdout, _stderr, code = await asyncio.wait_for(
            asyncio.gather(*tasks), timeout=CHECKER_TIMEOUT)
        if code not in (0, 1):
            return _check("ruff", "checker_error", reason="checker unavailable or exited unexpectedly")
        items = json.loads(stdout.decode("utf-8"))
        if not isinstance(items, list):
            raise ValueError("invalid checker response")
        diagnostics = []
        for item in items[:MAX_DIAGNOSTICS]:
            diagnostics.append(_diagnostic(
                str(item["code"]), str(item["message"]),
                int(item["location"]["row"]), int(item["location"]["column"])))
        result = _check("ruff", "failed" if items else "passed", diagnostics)
        result["truncated"] = len(items) > MAX_DIAGNOSTICS
        return result
    except asyncio.TimeoutError:
        return _check("ruff", "checker_error", reason="checker timed out")
    except _OutputLimit:
        return _check("ruff", "checker_error", reason="checker output limit exceeded")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return _check("ruff", "checker_error", reason="checker unavailable or returned invalid output")
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def validate_written_file(path: Path, content: str, *, enable_ruff: bool = False) -> dict:
    """Check only the supplied file content; never import or execute it."""
    checks: list[dict] = []
    suffix = path.suffix.lower()
    if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        checks.append(_check("size", "skipped", reason="source exceeds validation size limit"))
    elif suffix == ".py":
        try:
            compile(content, str(path), "exec", dont_inherit=True)
            checks.append(_check("python-compile", "passed"))
        except SyntaxError as exc:
            checks.append(_check("python-compile", "failed", [
                _diagnostic(type(exc).__name__, exc.msg, exc.lineno or 1, exc.offset or 1)]))
        except (ValueError, RecursionError, OverflowError):
            checks.append(_check("python-compile", "checker_error", reason="source cannot be compiled safely"))
        if enable_ruff and checks[0]["status"] == "passed":
            checks.append(await _ruff(path, content))
    elif suffix == ".json":
        try:
            def reject_constant(value: str) -> None:
                raise ValueError("non-standard JSON numeric constant")
            json.loads(content, parse_constant=reject_constant)
            checks.append(_check("json", "passed"))
        except json.JSONDecodeError as exc:
            checks.append(_check("json", "failed", [
                _diagnostic("JSONDecodeError", exc.msg, exc.lineno, exc.colno)]))
        except ValueError:
            checks.append(_check("json", "failed", [
                _diagnostic("InvalidJSONConstant", "non-standard JSON numeric constant")]))
        except RecursionError:
            checks.append(_check("json", "checker_error", reason="JSON nesting limit exceeded"))
    else:
        checks.append(_check("file-type", "skipped", reason="no validator for this file type"))
    statuses = {item["status"] for item in checks}
    status = next(s for s in ("failed", "checker_error", "passed", "skipped") if s in statuses)
    return {"status": status, "checks": checks}
