# Read-only GitHub PR review

NovaCore can collect a GitHub pull request into a local snapshot, then optionally
review that snapshot in an independent model context. It does not post comments,
approve, merge, push, modify the PR, or execute repository code.

## Collect first (no model request)

Install GitHub CLI (`gh`) and sign in locally with access to the repository. Do
not paste credentials into chat or commands. From the NovaCore checkout, run:

```powershell
python -m novacore.pr_review https://github.com/OWNER/REPO/pull/123 --output C:\review-output\pr-123-collection
```

Replace the URL and choose a **new** output directory. Existing directories are
never overwritten. This command does not load model configuration. It writes:

- `snapshot.json`: selected PR description, patches and fixed-revision content.
- `report.json`: machine-readable result and coverage.
- `report.md`: human-readable result.

Collection is not a model review: its verdict is `inconclusive`, and
`model_status` is `not_requested`, even when collection exits successfully.
Review the snapshot and uncovered-file reasons before authorizing transmission.

## Optional model review (may incur charges)

Configure the existing NovaCore model environment locally. Then explicitly
authorize one review in a different output directory:

```powershell
python -m novacore.pr_review https://github.com/OWNER/REPO/pull/123 --output C:\review-output\pr-123-review --confirm-paid
```

The command recollects the PR; it does not replay the previous snapshot. Check
the printed coverage and the recorded commit SHAs. `--confirm-paid` authorizes
transmitting the selected material in this invocation, not future reviews. No
automatic retry is made: SDK retries are disabled, output is limited to 2048
tokens, and the model request has a 90-second deadline. Truncated or invalid
responses are inconclusive. The existing model configuration is reused; no
additional provider or model-selection protocol is introduced.

PR text and code are untrusted evidence. The reviewer has no tools, repository
write access or main-session memory. Avoid submitting sensitive repositories
unless you have permission to send their code to your configured provider.
Path filtering skips common secret files, not all possible secrets in source or
PR descriptions. Prompt separation mitigates injection; it is not a guarantee
that model judgments cannot be manipulated.

## Coverage and outcomes

Snapshots record base/head SHAs and the merge-base SHA used for old content;
head content is read from the head repository, including forks. The PR is checked
again after collection. Concurrent updates mark the snapshot stale and skip
model review. Changes after that check do not retroactively update this report:
all conclusions apply only to the recorded snapshot, never a future PR version.

Defaults: 30 changed files, 64 KiB per content file or patch, 200 KiB selected
material; metadata is capped, no automatic related-code retrieval. Binary,
generated, sensitive-path, missing-patch, unavailable and over-budget files are
reported as uncovered. GitHub transport uses fixed-host GET requests, a 30-second
per-request deadline and 120-second collection budget. Large API responses are
rejected rather than silently assumed complete.

Findings must refer to supplied changed lines, include an exact source excerpt,
and use LEFT/RIGHT to distinguish deletion/addition. Renames use the new path
plus the side. Evidence anchoring does not establish that a claimed defect is
semantically correct; findings still require human judgment.

| Verdict | Meaning |
| --- | --- |
| `request_changes` | The reviewer reported anchored candidate issues. |
| `no_findings` | No issues were reported in a complete selected snapshot; not approval. |
| `inconclusive` | Not reviewed, partial coverage with no findings, stale, or failed review. |

Collection exits 0 for complete collection and 2 for incomplete/unavailable input.
Live review exits 0 for `no_findings`, 1 for `request_changes`, and 2 for
`inconclusive`. Review failures do not authorize merge. Nothing runs CI or checks
the whole application. This command does not repair or publish reviews.
For requirement-first generation, see [proposal then review](proposal-review.md);
for existing PR findings, see [human-selected repairs](pr-proposer.md).

If collection fails, check the URL, `gh` installation/login, repository access,
rate limits and output permissions. Raw authentication errors and environment
values are not copied into reports. There is no automatic fallback to broader
permissions or other hosts.
