# Offline repeat-job regression

From the repository root, in a disposable Python environment:

```powershell
python -m pip install -e .
python -m pip install pytest==9.1.1
python -m pytest tests/test_proposal_agents.py::test_repeat_job_does_not_spend_again -v -p no:cacheprovider --basetemp "<NEW-EXTERNAL-TEMP-DIRECTORY>"
```

Replace the temporary directory placeholder with a new disposable path: pytest manages its contents.
Requires Python >=3.11 and Git on PATH. No API key, GitHub login, network requests or paid model calls are required by the test. Installing dependencies may require network access.

The test is self-contained: it creates a temporary Git source and independent candidate worktree. Fake clients drive the actual Agent/tool loop. The first run must complete with two calls per role and change only the candidate. New clients then reopen the same durable job; the second invocation must raise the specific ReviewError before any additional client call, without changing the saved run record or file bytes.

The observed Windows/Python 3.13.12 result is in `repeat-job-result.txt`: 1 passed. This tests sequential re-entry using persisted state, not arbitrary business-tool idempotency, mid-request crash recovery or simultaneous-process races. It does not measure model quality or provider billing.
