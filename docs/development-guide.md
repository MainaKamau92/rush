# rush — Development Guide

Version 1.1 · 28 October 2026 · rush naming and Docker workflow

**Project decisions:** the application and CLI are named `rush`; existing TCR IDs
remain stable. Docker Compose is the supported development, test, and runtime
workflow; no host virtual environment is required. Finish a ticket, open its PR,
and wait for human review and merging before starting the next ticket.

## Purpose

This is the working agreement for **how we build the reviewer**. It applies to every implementation ticket and future change. It is not a new review skill or a feature the product must apply to other teams’ code.

The reviewer’s own repository must have meaningful tests, coverage checks, security checks, and merge gates. The product still does not perform general coverage assessments, test audits, or dedicated security scans of the repositories it reviews.

Authority: the project owner’s instructions, the technical spec, and the adaptations below. The attached playbook supplies practices, not an instruction to reproduce its JavaScript tooling, company-specific channels, or examples. Numerical thresholds below are initial project defaults chosen for setup; they are not CodeClimate standards or measured results.

## 1. Required backend layout

Use `app/` as the Python package. This replaces the earlier `reviewer/api`, `reviewer/storage`, and other proposed package paths. Keep the public command `rush` as the CLI entry point. FastAPI’s multi-file example supports separating application setup, dependencies, and routers; the fuller layout below is **our project standard**, including the folders requested by the project owner [R1].

| Path | Responsibility |
|---|---|
| `app/main.py` | Create the application, register routes, manage startup/shutdown. No review decisions. |
| `app/dependencies.py` | Construct and supply service, provider, and database objects. This is where the parts are connected. |
| `app/routers/` | HTTP input/output and authorization boundaries; delegate work to services. |
| `app/internal/` | Worker lifecycle and internal coordination; no second copy of business rules. |
| `app/internal/adapters/` | Concrete connections to GitHub, MCP, and model providers. |
| `app/provider/<capability>/abstract.py` | Abstract contract for a third-party capability; services depend on this module. |
| `app/provider/<capability>/base.py` | Select the concrete adapter class; do not create clients or instances at import time. |
| `app/core/` | Settings, logging, shared errors, and small infrastructure utilities. No catch-all business logic. |
| `app/models/` | Business concepts such as a review, finding, rule, exception, and learning proposal. |
| `app/schemas/` | Pydantic input/output and saved-record formats; shape validation, not workflow decisions. |
| `app/services/` | Classes implementing review decisions and business workflows. |
| `app/services/ports.py` | Small typed repository/storage interfaces; third-party contracts live under `app/provider/`. |
| `app/db/` | Connections, transactions, and persistence. Concrete repositories live in `app/db/repositories/`. |
| `app/db/migrations/` | Ordered, versioned database changes and their runner. |
| `app/cli.py` | Command-line input/output; call the same services used by the API. |
| `tests/unit/` | Most tests: business rules and service behavior using controlled substitutes for outside systems. |
| `tests/integration/` | Database/migration, provider contract, HTTP boundary, and worker interaction tests. |
| `tests/e2e/` | A small set of complete user journeys. |
| `tests/fixtures/` | Fictional examples, expected findings, and safe provider responses. |
| `skills/`, `scripts/`, `docs/` | Review skill bundles, development-check commands, and project documentation. |
| `.github/workflows/backend-ci.yml` | Required backend checks. Separate live-provider checks and release work from PR tests. |

Include normal Python package markers where needed, `pyproject.toml`, a dependency lock file, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, `README.md`, and `CONTRIBUTING.md`. Do not add an ORM, frontend, or a second database solely to satisfy a folder name; SQLite and versioned SQL migrations remain the MVP choice.

## 2. Classes, services, and provider boundaries

- Put business workflows in focused classes such as `ReviewService`, `RuleService`, `LearningService`, and `FindingService`. Give each class a clear responsibility and inject its dependencies through the constructor.
- Use small provider/repository interfaces with explicit inputs, outputs, errors, and cancellation behavior. Third-party contracts follow the owner's sample: an abstract class in `app/provider/<capability>/abstract.py`, its concrete implementation in `app/internal/adapters/`, and selection of the adapter class in `base.py`. Concrete classes such as `MetaModelAdapter`, `GitHubReviewAdapter`, and `SQLiteReviewRepository` implement the appropriate interfaces.
- Services work with these interfaces, not a vendor SDK, an HTTP client, or database queries. A provider translates third-party responses into our own records/errors before handing them back.
- The API and CLI call the same services. Routes must not decide rule precedence, approve learning, calculate review outcomes, or query the database directly.
- Prefer composing collaborating objects over deep inheritance. Do not create a generic base service or repository unless there is a concrete shared responsibility. Route handlers and small pure helper functions may remain functions; the business design remains class-based.
- Use Python names: `snake_case` modules/functions, `PascalCase` classes, and four-space indentation. Set Ruff formatting to a project line length of 88. Keep public service/provider methods typed and explain unusual decisions, not obvious syntax [R2].

**Enforcement:** use import-linter for forbidden dependencies from services/models into HTTP, database implementations, and concrete adapters. Add a small direct-import check for routers: no direct database/client/adapter imports; access goes through `dependencies.py`. Test the checks with deliberately forbidden imports. Keep `dependencies.py` as the explicit assembly exception so valid dependency wiring is not rejected. Human review checks responsibilities and useful class design; a linter cannot prove good OOP [R3].

**Working example:** `app/routers/health.py` receives a `SystemService` from
`app/dependencies.py`; the service depends on the `StateRepository` interface in
`app/services/ports.py`. Only the assembly module chooses
`app/db/repositories/state.py` as its concrete SQLite implementation. The CLI
uses the same assembly and service. A future model or MCP implementation belongs
in `app/internal/adapters/`, behind a service-owned interface; setup does not add
an unused vendor adapter merely to illustrate that folder.

For model access, `ModelAccessService` receives `ModelProviderAbstract` from
`app/provider/model/abstract.py`. `MetaModelAdapter` implements it;
`app/provider/model/base.py` selects that class as `ModelServiceProvider`.
Only `dependencies.py` constructs the HTTP client, adapter, and service. Services
must not import the selection module or concrete adapters. This keeps the
sample's contract/selection/adapter layout without global client instances.

## 3. Everyday development flow

1. Choose a ticket, understand its acceptance criteria, and identify the behavior or failure the change must protect.
2. Create a short-lived branch from current `main`. Use `story/TCR-010-local-review-report`, `task/TCR-001A-backend-layout`, or `bug/TCR-033-duplicate-comments`. Preserve the ticket ID when it is linked to a ClickUp task.
3. Write or update meaningful tests alongside the change. For a bug, first reproduce the unwanted behavior when practical, then show the fix makes that regression test pass.
4. Implement the behavior in the appropriate service and use provider/repository boundaries for outside dependencies.
5. Run local formatting, lint, type, architecture, and test checks using the same configuration as CI. Local coverage reports are optional; GitHub Actions enforces coverage thresholds. Pre-commit hooks provide quick feedback; they do not replace CI.
6. Open a focused PR linked to the ticket. Describe the behavior change, why it is needed, the tests run, and any limitation or migration.
7. Resolve review discussions and pass the required checks on the current change. Merge, update the ticket with verification evidence, and tag releases when appropriate.

### Commits and pull requests

Use the playbook’s ticket-first format: `TCR-010-story(review): explain findings with evidence`. Allowed types: `story`, `fix`, `docs`, `style`, `refactor`, `test`, `task`. Use a short imperative subject without a final period, separate any explanation with a blank line, and keep lines within the playbook’s 100-character limit. Put the ticket reference in the footer; mark completion there only when its work is complete.

PR title: `[TCR-010] Explain review findings with evidence`. The description contains **Description**, **Type of change**, **How this was tested**, **Checklist**, and **Ticket**. The checklist covers acceptance criteria, meaningful tests, correct service boundaries, migrations/configuration, sensitive data, and documentation. Validate branch/title formats automatically; review the usefulness of the description manually.

For ClickUp, retain Story/Task/Bug distinctions. Stories state intended user behavior; tasks explain enabling work; bugs include actual versus expected behavior, reproduction steps, and evidence. Existing TCR IDs remain stable. Completion language in a commit is documentation, not a promise that ClickUp will automatically change status.

### Version-control choices

Adopt small PRs into `main` for this MVP rather than the playbook’s full `develop`/release-branch workflow. This is a deliberate project simplification, not a claim that the playbook prescribes it. Keep the useful practices: ticket links, release tags, careful conflict resolution, and traceable hotfixes.

Rebase only your own working branch after checking for collaborators’ changes; never rewrite shared `main`. If a rewritten personal branch must be pushed, use a lease against the expected remote version. Use `revert` for undoing shared changes and a reviewed hotfix PR for urgent fixes. Rerun affected tests after conflict resolution or cherry-picking [R4].

Assign a reviewer when another teammate is available. Configure the solo/team review policy during setup; a solo author must not pretend to provide an independent approval. Do not adopt the playbook’s three-hour automatic permission to merge unreviewed work. No time-based exception bypasses failing CI. Protect workflow, coverage, architecture, and dependency configuration changes with maintainer review where the team supports it.

## 4. Testing for fidelity

**Tests protect behavior and prevent breaking changes. Coverage finds unexamined code; it is not the purpose of testing.**

| Test level | What to test | What to avoid |
|---|---|---|
| Unit — the majority | Rule precedence, exceptions/expiry, approval permissions, limits, finding identity, status transitions, privacy decisions, retries and error handling. | One test per method regardless of behavior; tests that repeat the implementation. |
| Integration | Real temporary SQLite transactions/migrations; provider request/response mapping with controlled HTTP responses; our signature checks, route-to-service wiring, persistence and worker recovery. | Requiring live accounts to check ordinary business logic; replacing the database in a test intended to prove its behavior. |
| End-to-end | A few acceptance journeys through the assembled service, including failures and corrections. | Duplicating every unit scenario through HTTP; treating a demo alone as a complete test suite. |

Use pytest, independent test data, and controlled clocks for expiry/deadline behavior. Substitute model/MCP/GitHub providers in ordinary CI. Test their real connection separately on trusted, explicitly selected code with demo-safe data. Test our handling of external failures, not whether a vendor’s implementation works internally.

Do not test FastAPI routing internals, Pydantic’s own validation algorithm, library getters/setters, or Python itself. It is useful to test that **our** endpoint rejects an unauthorized caller or maps **our** invalid input correctly. Assert observable outcomes and saved state; assert call counts only when they represent behavior such as preventing duplicate publication or limiting requests.

Acceptance criteria supply scenarios. A change is not Done because the coverage number increased. Reviewers should ask: **What regression would this test catch? Could broken behavior still pass it?** No empty assertions, mass snapshots without a purpose, duplicated tests for a percentage, or broad exclusions to make the number green.

### Coverage policy

Initial setup defaults: **80% combined statement/branch coverage across `app/`, with branch measurement enabled; 90% coverage of changed executable lines.** These are project guardrails, not evidence of correctness. Generate readable, XML, and JSON reports, including files never imported by tests. All executable application Python code is in scope; tests, third-party code, and generated artifacts are not. Migration behavior must have integration tests even when the migration itself is SQL and has no Python coverage score.

Use coverage.py’s branch-aware total for the overall threshold and diff-cover for changed executable lines. Compare against the actual PR base; missing history or missing coverage data fails the check rather than silently passing. A change with no executable lines reports “not applicable” for the changed-line metric, while the remaining jobs still run [R5–R6].

Enforce these thresholds in GitHub Actions. The workflow validates coverage data
and base history, runs diff-cover, and checks prerequisite job outcomes directly.
Local tests do not enforce coverage thresholds; local reports remain optional.

Once branches exist, add cases for meaningful alternative outcomes; critical approval, privacy, and required-check failures need explicit tests regardless of totals. Do not manufacture branches in the initial scaffold to obtain a score. No-tests-collected and unexpectedly absent application coverage fail setup. Lowering thresholds or adding exclusions requires a separate explained configuration change and approval under the recorded team policy.

## 5. Backend-only GitHub Actions merge gate

Implement the following jobs during initial setup. Use no frontend build or lint job. Start with the full backend suite on every PR so required checks cannot disappear because of path filters.

| Check | Tool / result required |
|---|---|
| Formatting and lint | `ruff format --check` and `ruff check` pass; check imports, naming, common mistakes, and agreed Python style. |
| Types | mypy passes for the application and public provider/service boundaries; no blanket ignore-all policy. |
| Architecture | Required folders, direct-import rules, and import-linter contracts pass. |
| Complexity and duplication | Ruff C901 with maximum complexity 10; Pylint duplicate-code check, starting with eight meaningful similar lines. Review narrowly justified exceptions instead of hiding warnings. |
| Tests and coverage | Unit/integration tests and deterministic acceptance tests pass, then the coverage policy above passes. Store test and coverage reports. |
| Dependencies and secrets | pip-audit reports no unapproved vulnerable dependency; Gitleaks reports no unapproved secret finding. Errors or unavailable audit data are failures, not clean results. |
| Python security checks | Bandit findings are addressed or narrowly documented as false positives. These scan our backend during development, not repositories reviewed by the product. |
| Migrations and packaging | Create a fresh database, upgrade a representative existing database preserving data, build/install the package, and start the service with safe test settings. Verify container startup once the Dockerfile exists; it is required for deployment acceptance. |
| Workflow/PR conventions | Check workflow configuration and branch/PR formats without running untrusted title or body text as shell commands. |
| **`backend-required`** | Run after every prerequisite, including failures; succeed only if every required prerequisite succeeded. |

CodeClimate is the aspiration for visibility into quality. The chosen local checks cover formatting, defects, types, complexity, duplication, coverage, and security; they do not claim to reproduce its scoring. CodeClimate’s documentation currently leads to Qlty, whose published categories include these areas. A hosted Qlty integration is optional, not a setup dependency [R7–R9].

### Make the gate real

- Trigger on PR creation/updates/reopening/ready-for-review and title edits as needed; also run checks on pushes to `main`. Add `merge_group` only if a merge queue is enabled. Keep job names stable.
- The final job uses `always()` with all required prerequisites and explicitly checks their results. A failed, cancelled, unexpectedly skipped, or missing job cannot yield success. Do not use `continue-on-error` for required checks [R10].
- Set timeouts and cancel obsolete runs for the same PR. Preserve diagnostic reports even after test failure. Do not cache credentials or reuse untrusted artifacts in privileged release jobs.
- Default to `contents: read`, disable persisted checkout credentials, and pin actions to verified immutable revisions (or the supported dependency-lock mechanism). PR tests have no production/model/MCP secrets and do not run on privileged self-hosted runners. Do not use `pull_request_target` to execute contributed code [R11].
- Configure the repository’s ruleset/branch protection to **require `backend-required`**, require an up-to-date change, and prevent direct/force pushes to the protected branch. Set the expected check source where supported. No routine bypass for maintainers. A YAML file alone does not enforce merging [R12].
- Agree the review-approval policy for solo versus team work; require independent approval when there is an eligible teammate, resolve discussions, and invalidate stale approval after changes where configured. Never weaken failing machine checks because a reviewer is unavailable.
- Verify with temporary PRs: failing test, insufficient coverage, lint/type error, forbidden import, complexity/duplication violation, scanner test fixture, skipped job, and a newer commit arriving mid-run. Show merging remains blocked, then restore passing work. Never introduce a real secret to test detection.

**Quality changes cannot silently disable the checks that judge them.** Require review of changes to workflows, thresholds, exclusions, allowlists, and architecture rules. A solo setup records explicit self-review and a gate-failure demonstration; it must not claim the same independent protection as a multi-maintainer repository.

## 6. Secure configuration and repeatable operation

Borrow the playbook’s development-security practices and the applicable Twelve-Factor principles:

- Keep credentials, private personal data, local databases, and raw private source captures out of Git and test fixtures. Use synthetic data. Provide `.env.example` with names and safe placeholders only.
- Load deployment-specific settings from the environment through one settings class; reject missing required settings without echoing secrets. Keep team review rules version-controlled separately from deployment credentials.
- If a secret is committed or logged, revoke/rotate it first, assess access and replace dependent credentials, then coordinate any necessary history/log cleanup. A force-push cannot make an exposed credential safe [R13].
- Declare and lock dependencies, use Docker images for isolation, and keep development/test/production aligned on the selected Python and SQLite versions. No host venv is required.
- Build an artifact once; combine it with environment settings to release it, then run that release. Do not install dependencies or change schemas as an uncontrolled side effect of every server start.
- Run migrations and maintenance as explicit one-off commands against the same release/configuration; ensure only one migration runner acts at a time. Test fresh setup and upgrade/data preservation. Document restore or roll-forward recovery for destructive changes.
- Make provider endpoints and database location configurable behind the agreed interfaces. Logs go to stdout/stderr with run/request IDs and redaction; deployment handles collection.
- Persist jobs, approvals, and review state in the database, not process memory. Start cleanly, stop accepting new work on shutdown, preserve unfinished jobs, and recover on restart.
- Keep the MVP’s **single instance with SQLite on a persistent volume**. This is a deliberate scaling limitation, not full Twelve-Factor horizontal scalability. Do not run multiple app/worker replicas against a shared SQLite file or introduce Kubernetes merely to copy the playbook [R14].

## 7. Initial setup and completion evidence

TCR-001 is the setup parent. Complete its five subtasks in the TCR-001 PR. Wait for human review and merging before starting access experiments or fictional-example work under later tickets.

| Subtask | Deliverable |
|---|---|
| TCR-001A | Required folder layout, service/provider boundaries, and executable architecture checks. |
| TCR-001B | Branch/commit/PR templates, contribution guide, and recorded team review policy. |
| TCR-001C | Behavior-focused test setup and honest coverage enforcement. |
| TCR-001D | Backend workflow, actual required-check protection, and failure demonstrations. |
| TCR-001E | Safe configuration, dependency locking, migration setup, and repeatable startup/recovery. |

Keep the README focused on purpose, setup, running, tests, endpoints, contribution, and deployment. Store this agreement as `docs/development-guide.md` in the future repository and link it from `CONTRIBUTING.md`. Add the layout and testing rules to the repository’s agent instructions so future coding work follows them too. Documentation and configuration must be updated together when the team changes a rule.

This document specifies the work to implement. It does **not** establish that a product repository, workflow, or branch protection has already been configured.

## Appendix — Playbook review and link checks

All six requested sections were read from `engineering-playbook-master.zip`: Conventions, Security, Style Guide (Python and linting), Testing, Twelve Factor App, and Version Control. The Testing guide has no external links. Internal references back to Conventions and Twelve Factor App were resolved within the ZIP.

| Playbook link or guidance | Reading result and decision |
|---|---|
| [PEP 8](https://peps.python.org/pep-0008/) | Read; Python naming/readability apply. Our formatter settings are explicit project choices. |
| [365Git commit messages](https://365git.tumblr.com/post/3308646748/writing-git-commit-messages) and [Tim Pope’s commit article](https://tbaggery.com/2008/04/19/a-note-about-git-commit-messages.html) | Read; retain concise subjects, motivation, and separation of subject/body. The playbook’s ticket format remains our chosen convention. |
| [Angular commit-convention document](https://docs.google.com/document/d/1QrDFcIiPjSLDn3EL15IJygNPiHORgU1_OOAqWjiDU5Y/) | Page shell accessible; document body/export unavailable. Do not claim its full contents were verified. The supplied playbook already contains the convention we adapt. |
| [Git recovery guide](https://sethrobertson.github.io/GitFixUm/fixup.html) | Read; choose recovery according to whether history is shared. Use GitHub’s current guidance for exposed-secret remediation. |
| [Python section of the linked linter list](https://github.com/AndelaOSP/awesome-linters/blob/master/README.md#python) | Read through GitHub; use current tool documentation for selected checks rather than copying historical package choices. |
| [Atlassian Gitflow](https://www.atlassian.com/git/tutorials/comparing-workflows/gitflow-workflow) | Direct reader rejected its content type; search confirmed the page, but full text was not read. Full Gitflow was read in the supplied playbook; our simpler branching choice is explicit. |
| [Git tagging](https://git-scm.com/book/en/v2/Git-Basics-Tagging), [rebase](https://git-scm.com/docs/git-rebase), and [GitHub conflict resolution](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/resolving-a-merge-conflict-using-the-command-line) | Read applicable sections; preserve release references and resolve conflicts deliberately. |
| [Atlassian force-with-lease article](https://developer.atlassian.com/blog/2015/04/force-with-lease/) | Redirect was inaccessible. Read the official Git push documentation instead. |
| [Pivotal Tracker integration](https://www.pivotaltracker.com/integrations/GitHub/) | Unavailable through the reader and not part of this ClickUp workflow. No integration behavior assumed. |
| [Shared microservice example](https://github.com/andela/micro-shared) | GitHub returned 404; no content relied upon. URLs inside the Node example configuration are illustrative, not adopted dependencies. |
| [Elastic](https://www.elastic.co/products), [Splunk](https://splunk.com/), [Cloud Logging](https://cloud.google.com/logging) | Read the linked product pages; these illustrate external log collection, not required purchases or integrations. |
| [npm](https://www.npmjs.com/) and [Yarn dotenv link](https://yarnpkg.com/en/package/dotenv) | Respectively blocked and unavailable in the reader; JavaScript-specific setup is not adopted. |

Other language/frontend style guides, company-only team/console links, and decorative screenshots are outside the Python backend reading scope. They are not claimed as reviewed guidance. No inaccessible linked page is treated as verified.

### Current implementation references

| Ref | Official source used |
|---|---|
| R1 | [FastAPI: larger applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) |
| R2 | [PEP 8](https://peps.python.org/pep-0008/) |
| R3 | [Import-linter contracts](https://import-linter.readthedocs.io/en/stable/contract_types.html) |
| R4 | [Git push / force-with-lease](https://git-scm.com/docs/git-push), [Git rebase](https://git-scm.com/docs/git-rebase), [Git tagging](https://git-scm.com/book/en/v2/Git-Basics-Tagging) |
| R5 | [coverage.py JSON reports](https://coverage.readthedocs.io/en/latest/commands/cmd_json.html) |
| R6 | [diff-cover](https://github.com/Bachmann1234/diff_cover) |
| R7 | [Ruff complexity check](https://docs.astral.sh/ruff/rules/complex-structure/) |
| R8 | [Pylint duplicate-code check](https://pylint.readthedocs.io/en/latest/user_guide/messages/refactor/duplicate-code.html) |
| R9 | [CodeClimate / Qlty documentation](https://docs.codeclimate.com/), [Qlty maintainability metrics](https://docs.qlty.sh/cloud/maintainability/metrics) |
| R10 | [GitHub: troubleshooting required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks) |
| R11 | [GitHub: secure Actions use](https://docs.github.com/en/actions/reference/security/secure-use) |
| R12 | [GitHub: protected branches](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches) |
| R13 | [GitHub: removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) |
| R14 | [Twelve-Factor overview](https://12factor.net/), [configuration](https://12factor.net/config), [processes](https://12factor.net/processes), [administrative processes](https://12factor.net/admin-processes) |

Verification: six of six requested playbook sections inspected. Link limitations are recorded above. The layout, thresholds, tool choices, and workflow adaptations are project decisions; sources substantiate their underlying mechanisms, not an assertion that enforcement is already active.
