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

TCR-001 has passed local verification; GitHub CI and merge-gate proof remain
pending. The ticket is not accepted until its PR is reviewed and merged. The PR is the review boundary, not permission to
start TCR-002 before merge.

| Subtask | Evidence | Status |
|---|---|---|
| TCR-001A | Required package layout, constructor-injected system service, architecture failure fixtures | Locally verified; GitHub CI pending |
| TCR-001B | Contribution/agent rules, ticket templates, Docker hooks, branch/PR checker | Locally verified; GitHub CI pending |
| TCR-001C | Behavioral tests, real SQLite upgrade/rollback/restore, coverage and failure fixtures | Locally verified; GitHub CI pending |
| TCR-001D | Backend CI, protected `main`, actual failing-check/merge-block demonstration | Locally verified; GitHub CI pending |
| TCR-001E | Locked images, explicit migration command, safe settings, backup/restore and restart | Locally verified; GitHub CI pending |

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
