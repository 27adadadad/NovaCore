# Offline continuous integration

`.github/workflows/ci.yml` runs on push, pull_request and manual dispatch.
The matrix covers Windows/Linux and Python 3.11/3.13. Each job installs dependencies,
runs the public `tests` directory, builds a wheel and installs/smoke-checks that wheel
outside the source checkout. JUnit XML and wheel artifacts are retained for seven days,
including available reports after a failed job. Runtime per job is capped at 15 minutes.

Development dependencies are in `requirements-dev.txt`. Run locally in a disposable venv:

```text
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest tests -v -p no:cacheprovider --junitxml=reports/junit.xml
python -m pip wheel --no-deps --no-build-isolation --no-index . --wheel-dir dist
python scripts/check_wheel.py dist
```

The wheel checker reinstalls the package in the current interpreter. Do not run it in
a shared environment; use a dedicated disposable venv and an empty wheel output folder.

No model keys are configured and the public suite uses FakeClients/local commands.
Installing dependencies requires network access; offline refers to model/tool fixtures,
not an air-gapped runner. Existing local-only experiments are NOT included in CI coverage.
Actions are commit-pinned, checkout credentials are not persisted, and GITHUB_TOKEN has
contents:read only. Do not use pull_request_target to execute untrusted PR code with secrets.

This is CI, not CD: there is no release publication, deployment, automatic merge or
branch-protection change. Required checks must be configured separately by a maintainer.
The workflow currently lives on codex/pr-review; manual dispatch visibility depends on
the default branch configuration. An actual Actions run result, not a local pytest run,
establishes whether a remote matrix job passed.
