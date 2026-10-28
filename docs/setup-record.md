# TCR-001 setup record

## Decisions

- Application, CLI, images and Compose project: **rush**. Existing TCR IDs stay.
- Public repository: https://github.com/MainaKamau92/rush.
- Maintainer and initial rule approver: MainaKamau92, GitHub user ID 26567020.
  Product approval/authorization enforcement is future work, not enabled here.
- License: MIT, explicitly selected by the project owner on 28 October 2026.
- Runtime: Docker Compose; no host virtual environment. Python 3.12.13;
  uv 0.11.21 resolves `uv.lock`; containers install its hash-checked requirements
  exports using system pip, with no virtual environment in the run workflow.
- Setup branch: `task/TCR-001-project-setup`; one PR for the setup parent and its
  TCR-001A–001E subtasks. Wait for human review and merging before the next ticket.
- Solo review policy: owner self-review, without claiming independent approval.
  Add independent required approval when an eligible teammate is available.
- Approved settings: reviewed configuration from protected `main`; deployment
  settings are environment inputs. Product policy registries come in later tickets.
- Single runtime instance and persistent local-volume SQLite; no distributed worker.

## Local runtime evidence

The Docker runtime smoke test completed with Python 3.12.13, SQLite 3.46.1,
explicit migration to schema 1, healthy container readiness, and a successful
`rush health` command. This is setup behavior, not a product-review run.

## Acceptance evidence

TCR-001 has passed local verification and GitHub CI, including the deliberate
merge-gate failure proof. It awaits human review and merging in PR #2; no later
ticket starts before that merge. The ticket is not marked accepted by this record.

| Subtask | Evidence | Status |
|---|---|---|
| TCR-001A | Required package layout, constructor-injected system service, architecture failure fixtures | Ready for human review |
| TCR-001B | Contribution/agent rules, ticket templates, Docker hooks, branch/PR checker | Ready for human review |
| TCR-001C | Behavioral tests, real SQLite upgrade/rollback/restore, coverage and failure fixtures | Ready for human review |
| TCR-001D | Backend CI, protected `main`, actual failing-check/merge-block demonstration | Ready for human review |
| TCR-001E | Locked images, explicit migration command, safe settings, backup/restore and restart | Ready for human review |

## Product limitations

There are no model adapters, MCP connections, review findings, jobs, dialogue, or
approved learning yet. Account access, exact model IDs, costs, and connector
authorization are unverified and belong to TCR-002/TCR-003. Do not infer them
from this machine's unrelated app connections.

## Local verification results

- Both canonical Docker targets build successfully from hash-checked exports.
- 34 tests pass; combined statement/branch coverage is 99.31%.
- Changed executable lines: 250 of 251 covered, above the 90% gate.
- Formatting/lint, strict types, both import-linter contracts, the direct-import
  checker, duplication checks, actionlint, and Bandit pass.
- The complete locked third-party dependency export reports no known
  vulnerabilities; an unavailable vulnerability service is not treated as success.
- Gitleaks reports no leaks in staged files. A fictional credential fixture is
  detected and rejected; local environment files are ignored and not published.
- Deliberate undefined-name, type, complexity, duplicate-code, inadequate-coverage,
  missing-coverage, and incompatible-schema regression fixtures are rejected.
  Gate unit cases reject failed, cancelled, skipped, neutral and missing results.
- The built runtime migrates explicitly, keeps state across container replacement
  and restart, exports a consistent backup, and restores it successfully in a
  disposable container. The persistent volume was not deleted or overwritten.
- Ordinary tests have one upstream TestClient HTTPX deprecation warning; no
  warnings are suppressed. Product HTTP/model adapters are not implemented here.

Local reports are generated under ignored `reports/` and coverage files. CI
uploads test/coverage artifacts; GitHub run links below are the shared evidence.

## GitHub verification

- Setup PR: [#2](https://github.com/MainaKamau92/rush/pull/2), branch
  `task/TCR-001-project-setup`; no automatic merge is enabled.
- [Passing run at 8742223](https://github.com/MainaKamau92/rush/actions/runs/40732568410):
  all six jobs succeeded, including `backend-required`. This verifies the Python
  lock-tool image correction in addition to the application and quality checks.
- [Temporary proof PR #3](https://github.com/MainaKamau92/rush/pull/3), source
  `e48accfb830498224538e80824526c5622d50042`:
  [isolated negative-control run](https://github.com/MainaKamau92/rush/actions/runs/40733231256)
  had tests fail (the intentional assertion and insufficient coverage), quality
  skipped, conventions/security/package succeed, and `backend-required` fail.
  GitHub reported `draft: false` and `mergeable_state: blocked`; no merge was
  attempted. The temporary PR is closed without merging; the setup branch keeps
  passing tests and the original coverage thresholds.
- Main protection requires the up-to-date `backend-required` result specifically
  from GitHub Actions app ID 15368, enforces administrators, requires PRs and
  resolved conversations, and disallows force pushes/deletion. Solo human review
  is documented; independent approval is not claimed.
- Current-revision run links and obsolete-run cancellation evidence are in PR #2.
  The owner must review the exact final revision and merge it before TCR-002.
