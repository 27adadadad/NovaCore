# Human-selected PR repairs

For requirement-first generation before any review exists, use
[proposal then review](proposal-review.md). This page describes the separate
entry for repairing selected findings from an existing PR review.

The Proposer consumes a completed local PR review and fixes only explicitly selected
findings. It never commits, pushes, posts a review, or merges. Model access remains
opt-in for each stage. A report with `no_findings` cannot start a repair.

## 1. Select and prepare (no model request)

Read `report.json` and choose findings by their order in `findings` (starting at 1).
The local source repository must be checked out at that report's PR head commit.
Do not reset a checkout containing your work; use a separate checkout if needed.

```powershell
python -m novacore.pr_proposer --review-dir C:\reviews\pr-review --repo C:\src\target --finding 1 --output C:\reviews\fix-job
```

Repeat `--finding` to select additional findings. Output must be a new directory
outside the source checkout. The source checkout's dirty files are not read or
overwritten. The selected source blobs must exactly match the reviewed snapshot;
the GitHub PR's current base/head must still match the review. A stale review,
fabricated source anchor or unsupported file is rejected before worktree creation.

This creates a `codex/pr-fix-...` branch in an **isolated sparse worktree** under
`fix-job/worktree`. Only the selected files are materialized; other tracked files
remain in Git's index with `skip-worktree`, so absence is not treated as deletion.
This avoids copying unrelated files and bypasses checkout hooks and smudge filters.
It is not a full runnable application checkout. Do not run project builds here or
manually clear the skip-worktree flags without understanding their effect.

Inspect `fix-report.json` for the selected findings, allowed files and original
hashes. First version limits: five regular, non-executable text files, each at most
64 KiB; only existing files can be replaced, not deleted or renamed. Recreating a
file removed by the PR is unsupported. Cross-file fixes outside the selected set
require a new, explicitly selected job; the model cannot expand its own scope.

## 2. Authorize one proposal

Configure the existing model environment locally without sharing credentials.
After checking the prepared scope, authorize one request:

```powershell
python -m novacore.pr_proposer --propose-fix C:\reviews\fix-job --confirm-paid
```

Without `--confirm-paid`, this existing-job command only displays the current
status. With authorization, one independent model request proposes strict JSON
file replacements. No tools are exposed. SDK retries are disabled; request time
is limited to 90 seconds and output to 2048 tokens. Larger fixes may not fit and
are rejected rather than silently applied. Invalid responses and cancellation
consume the job's attempt; there is no automatic retry.

All edits must match allowed paths and original SHA256 hashes before any write.
The PR version and local workspace are checked again after the model returns;
concurrent user edits are preserved rather than overwritten. A write failure
attempts to restore original bytes and records whether restoration succeeded.

`changes.patch` records the actual Git diff. `fix-report.json` records the resulting
file hashes and syntax/JSON diagnostics, reusing the existing post-write checker
with optional external analysis disabled. It never imports or executes generated
code, project commands, hooks, CI or repository scripts.

- `candidate_ready`: a local candidate exists without failed built-in checks;
  it does **not** mean the issue is fixed or the application works.
- `validation_failed`: candidate is preserved with diagnostics; do not call it done.
- `invalid_proposal` / `proposal_request_failed`: no valid proposal was applied.
- `proposal_started`: an interrupted or concurrently invalidated attempt requires
  manual inspection; do not automatically resume or retry.

Review the patch yourself. Automated source anchoring and syntax checks do not
prove semantic correctness. Reports are local records, not signed security attestations;
do not edit their identities, selection lists or hashes to bypass the gates.

## 3. Review the local candidate, not the old remote PR

Prepare a local review without a model call:

```powershell
python -m novacore.pr_proposer --review-fix C:\reviews\fix-job
```

This builds `local-snapshot.json` from the candidate content and original PR
context. `local-review-preparation.json/.md` explicitly state that the model was
not requested. After separate authorization, review that same fixed candidate:

```powershell
python -m novacore.pr_proposer --review-fix C:\reviews\fix-job --confirm-paid
```

That is one **additional**, independently authorized model request, not part of
the proposal budget. It writes `local-review.json/.md` without overwriting the
preparation report. It cannot be repeated for the same job. Candidate hashes are
checked before and after review. The result is tagged `local_uncommitted_fix`:
`head_sha` identifies the original remote PR commit, while `candidate_hashes`
identify the local edits. Do not report the old remote PR as if it already contained
these unpushed changes. This step is not a whole-repository review.

You decide whether to keep, commit, push or discard the candidate. None of those
actions is automatic. A successful model review is not authorization to merge.
To discard a job, first inspect the worktree for your own edits, then use standard
Git worktree/branch cleanup; never blindly recursively delete it.

## Failure handling and limitations

Existing output directories and review reports are not overwritten. Unsupported
encodings, executable modes, symlinks, changed identities, extra materialized files,
missing permissions and inaccessible PR metadata stop the workflow. Typical API
issues require checking `gh` login/access or rate limits; the program does not
expose authentication stderr or broaden permissions. A partially created worktree
may remain after a filesystem/Git error, and should be inspected before cleanup.

Path and version checks prevent normal accidental overwrites; they are not an OS
security boundary against another process actively tampering with the worktree.
The model can still propose a logically wrong or harmful change to an allowed file.
Human review remains necessary. Common secret-path filtering is not complete secret
detection; only transmit code you are authorized to send to the configured provider.
