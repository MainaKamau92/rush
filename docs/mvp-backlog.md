# rush — MVP Requirements and Tickets

Version 1.4 · 30 October 2026 · Meta-only, local demo scope

**Source:** [Technical Specification v0.5 — Python/FastAPI](technical-spec.md), paired with `docs/development-guide.md`. This backlog turns the agreed design into implementation and testing tasks. It does not create tasks in ClickUp.

**Working decisions:** use `rush` for the application and CLI; preserve TCR IDs.
Use Docker Compose for running, testing, and development tools, with no host venv.
Work on one ticket, or one merged ticket group, at a time: finish it, open its
PR, and wait for human review and merging before starting the next. There is no
parallel development. TCR-001A–001E are subtasks delivered in the TCR-001 parent PR.

**Owner scope update, 29 October 2026:** use Meta models for the hackathon and retain replaceable provider interfaces. No second provider or credential is required now. TCR-002, TCR-024, and A13 follow this change; cross-provider verification is deferred.

**Owner scope update, 30 October 2026:** the MVP is built for a local demo.
rush runs on a developer machine through Docker Compose; there is no hosted
deployment, and everything, including the demo, is tested locally. The GitHub
App remains the main way to use rush, with PR events forwarded to the locally
running service; the command line serves local reviews. Work the demo does not
need is removed (see [Removed from the MVP](#removed-from-the-mvp)), and closely
linked tickets are merged so each group is delivered in one PR. Where the
technical specification describes removed work, this backlog's scope applies.

**Progress, 30 October 2026:** TCR-001 (with TCR-001A–001E), TCR-002–014,
and TCR-033 are merged. Seven work items remain; the next is TCR-015 + TCR-016.

**Development versus product behavior:** the playbook guides how we develop this backend. Our own repository must pass meaningful tests, coverage and quality checks. Those checks do not become coverage-audit or security-scanning features in the reviewer. The required FastAPI layout, class-based services, and provider pattern apply to every implementation ticket below.

## How to use this backlog

Each numbered heading is a ticket title. Copy its description and acceptance criteria into ClickUp, keep its ID, and use the stage as its group. “Depends on” identifies work needed before the ticket can be accepted; start another ticket only after the current ticket PR has been reviewed and merged.

**Merged tickets:** a heading that joins IDs, such as `TCR-009 + TCR-010`, is one
unit of work delivered in one PR; keep every ID in ClickUp. Lead with the lowest
ID: branch `task/TCR-009-tcr-010-<short-description>`, PR title
`[TCR-009] <Title> (TCR-010)`, commit subject `TCR-009-task(<scope>): <subject>`,
and footer `Refs: TCR-009, TCR-010`. The PR gives evidence for every listed
acceptance criterion.

**Default fields:** Status = To do; Assignee = Unassigned; Scope = Required for MVP. Assign owners and dates when work is scheduled. The order shows dependencies, not a promise that every ticket takes the same effort.

**Suggested statuses:** To do → In progress → Ready to verify → Done; use Blocked when a dependency or access problem prevents progress.

**Done means:** all acceptance criteria have been checked, relevant tests pass, and changed setup or behavior is documented. Add one short completion note: **what changed; evidence link; any remaining limitation**. Use a test result, example review, or screenshot as evidence where useful. Do not mark work Done on the strength of a code change alone.

Every implementation ticket also follows the development guide: business logic stays in service classes; outside calls use injected provider/repository interfaces; tests guard behavior and regressions rather than framework internals or a target percentage; the required backend CI gate passes. TCR-001 has five setup subtasks, TCR-001A–001E. Existing ticket IDs remain unchanged.

**Terms:** A PR is a proposed code change on GitHub. A review skill is a reusable set of review instructions with examples that check it works. MCP is the connection used to read tickets and team documents.

## The development story

| Stage | Tickets | What should work by the end |
|---|---|---|
| 0. Set up and prove access | TCR-001–004, including TCR-001A–001E | Done: layout, OOP boundaries, meaningful tests, secure configuration, and a backend merge gate; Meta models, live context, and demo examples are ready. |
| 1. Review a change locally | TCR-005–010 | A local review finds supported issues and explains its limits. TCR-005–008 are done. |
| 2. Understand the team | TCR-011–014 | Reviews use relevant tickets, approved standards, and valid exceptions without exposing private information. |
| 3. Review on GitHub | TCR-015–019 | The locally running service reviews real PRs, updates its review after new commits, and reports the outcome honestly. |
| 4. Explain and learn | TCR-020–023 | People can question findings, adjust explanations, and approve learning. |
| 5. Prove the MVP locally | TCR-024, TCR-028–032 | Full journeys pass locally, Meta models are compared, and evidence and the demo are ready. |

**Remaining work, in order (one PR each):**

| Order | Work item | Tickets |
|---|---|---|
| 1 | Review a change locally with tested skills | TCR-009 + TCR-010 |
| 2 | Retrieve ticket and guideline context safely | TCR-011 + TCR-014 |
| 3 | Apply approved standards and exceptions | TCR-012 + TCR-013 |
| 4 | Start reviews from GitHub PRs on the local service | TCR-015 + TCR-016 |
| 5 | Publish, update, and report reviews on the PR | TCR-017 + TCR-018 + TCR-019 |
| 6 | Explain and reassess findings | TCR-020 + TCR-021 |
| 7 | Propose, test, and approve team learning | TCR-022 + TCR-023 |
| 8 | Verify the PR review journey locally | TCR-028 + TCR-031 |
| 9 | Verify team control, honesty, and safety locally | TCR-029 + TCR-030 |
| 10 | Compare Meta models and prepare the local demo | TCR-024 + TCR-032 |

**Scope stays small:** one repository, one team, selected Meta models, and a small skill set. Demonstrate one ticket source and one approved guideline source through live MCP connections. ClickUp tickets plus Notion guidelines is the preferred setup; ClickUp tasks plus Docs is an allowed alternative.

**Outside this MVP:** hosted deployment, CI review mode, required merge checks, data retention and backup tooling, a custom dashboard, marketplace, extra integrations, broad repository exploration, dedicated security scanning, coverage checks, general test-quality reviews, running the application’s tests, code generation, automatic fixes/merges, and post-merge work. Tests of the reviewer itself are required. Apparent security issues may still be reported when supported by the changed code.

## Stage 0 — Set up and prove access

### TCR-001 — Set up the Python project and working agreements

**Depends on:** None. **Spec:** §§1–2, 13.

**Description:** Create a small, repeatable starting point for development and agree who controls the reviewer’s settings.

**Acceptance criteria**

- Complete TCR-001A–001E, with linked evidence for layout, workflow, testing, CI/merge enforcement, and secure operation.
- A fresh checkout installs from the lock file, starts the FastAPI service, and runs the command-line tool using the documented setup.
- Record the repository, approved settings location, maintainers, rule approvers, solo/team review policy, and open-source license.
- Put the development guide in the repository and link it from contribution and agent instructions; it governs later work.
- Demonstrate that a deliberately failing required check blocks merging, then restore passing work. Documentation alone does not complete setup.

### TCR-001A — Establish the FastAPI layout and service boundaries

**Type:** Task; subtask of TCR-001. **Depends on:** None. **Spec:** §2 and development guide §§1–2.

**Description:** Give every future change a predictable home and keep business decisions separate from transport and outside services.

**Acceptance criteria**

- Create `app/main.py`, `dependencies.py`, `routers/`, `internal/`, `core/`, `models/`, `schemas/`, `services/`, and `db/migrations/`, plus top-level `tests/`. Follow the guide’s responsibilities; keep the CLI name `rush`.
- Place business workflows in focused service classes; define typed provider/repository interfaces and inject implementations through constructors.
- Keep GitHub/MCP/model connections in adapters and database work in repositories. Routes and the CLI delegate to services rather than containing business rules.
- Add architecture checks that reject forbidden imports, and demonstrate that a router database call or service vendor-client import fails them.
- Document a small example showing where a route, service, interface, and adapter belong. Avoid unused base classes and forced wrappers around simple helpers.

### TCR-001B — Establish the contribution and version-control workflow

**Type:** Task; subtask of TCR-001. **Depends on:** None. **Spec:** Development guide §3.

**Description:** Make the history explain which ticket changed behavior, why, and how it was verified.

**Acceptance criteria**

- Document short-lived ticket-linked branches into `main`, commit format, PR title/description, conflict handling, release tags, and hotfix flow.
- Add PR and Story/Task/Bug templates using ClickUp-neutral ticket references; preserve existing TCR IDs.
- Require PR descriptions to state the change, reason, tests, and relevant limitations or migrations. Add fast local checks through pre-commit hooks.
- Record the solo/team review policy and controls for changing CI, exclusions, and quality thresholds. A deadline never permits bypassing failing checks.
- Document README/setup/testing/contribution requirements and safe handling of shared history. Validate branch/PR format without executing user-supplied text.

### TCR-001C — Set up meaningful tests and coverage checks

**Type:** Task; subtask of TCR-001. **Depends on:** TCR-001A. **Spec:** §10 and development guide §4.

**Description:** Build confidence that behavior stays correct; use coverage to find gaps, not to justify artificial tests.

**Acceptance criteria**

- Set up unit, integration, and end-to-end test folders with independent fixtures. Focus most tests on business/service behavior and regressions, not framework internals or a test for every method.
- Use controlled provider responses in ordinary CI and a real temporary SQLite database for storage/migration tests. Keep live-provider runs separate and trusted.
- Test actual initial behavior, such as missing required configuration and safe startup, without manufacturing code just to raise a score.
- Enable branch measurement and the starting gates: 80% combined statement/branch coverage across `app/`, and 90% of changed executable lines. Report missing data as a failure and no changed executable lines as not applicable.
- Require purpose and approval for exclusions or lowered thresholds. Show an uncovered change fails the gate and a meaningful regression test detects broken behavior.

### TCR-001D — Enforce backend quality checks before merging

**Type:** Task; subtask of TCR-001. **Depends on:** TCR-001A, TCR-001B, TCR-001C, TCR-001E. **Spec:** §2 and development guide §5.

**Description:** Build the backend-only GitHub Actions workflow and make its result a real merge requirement.

**Acceptance criteria**

- Run formatting/lint, types, architecture, complexity/duplication, tests/coverage, dependency/secret/security checks, and migration/package checks with pinned tools and recorded settings.
- Make `backend-required` run after all prerequisite jobs and fail if any required result is failed, cancelled, missing, or unexpectedly skipped. It must not disappear because of path filters.
- Configure protected-branch/ruleset requirements for that check and current code. Prevent direct/force pushes and routine bypass; record the agreed human review policy.
- PR jobs use minimal permissions and no live model/MCP or production secrets. Do not execute contributed code through privileged event triggers.
- Save test/coverage reports, bound runtime, cancel stale runs, and preserve useful diagnostics on failure.
- Demonstrate that broken tests, inadequate coverage, lint/type/architecture violations, scanner fixtures, and skipped jobs block merging; restore green afterward. Do not claim CodeClimate-equivalent scoring.

### TCR-001E — Set up secure configuration and repeatable operation

**Type:** Task; subtask of TCR-001. **Depends on:** TCR-001A. **Spec:** §§2, 9 and development guide §6.

**Description:** Make development, testing, and deployment reproducible without putting private information into the repository.

**Acceptance criteria**

- Lock dependencies, validate environment-based deployment settings, and provide safe examples. Ignore secrets, local databases, private data, and source captures in Git.
- Document leaked-secret response: revoke/rotate and assess exposure before any coordinated cleanup. A rewritten commit is not treated as containment.
- Add ordered database migrations and an explicit migration command; verify fresh creation and upgrade/data preservation. Server startup does not silently run competing schema changes.
- Separate build, release, and run; log safely to stdout/stderr, manage startup/shutdown, and record backup/recovery steps.
- Keep SQLite on persistent storage and the MVP single-instance; document the scaling limitation instead of claiming full Twelve-Factor compliance.

### TCR-002 — Confirm access to selected Meta models

**Depends on:** TCR-001A. **Spec:** §§7, 13.

**Description:** Resolve account and model-access risks before building the review workflow around them.

**Acceptance criteria**

- Small requests succeed through two selected Meta models from Python. Other providers are deferred by the owner; keep an injected provider-neutral interface without claiming cross-provider compatibility.
- Exact model names, connection settings, available features, request limits, and credential setup are recorded without exposing secrets.
- Available credits, usage charges, and the selected data-handling settings are checked; anything not confirmed is clearly marked unknown.
- The application reports an unavailable model clearly and never silently switches provider or data-handling settings.

### TCR-003 — Confirm access to the ticket and guideline sources

**Depends on:** TCR-001A. **Spec:** §§5, 13.

**Description:** Prove that the chosen team information can be read through real MCP connections.

**Acceptance criteria**

- Choose and record the demo’s ticket and guideline sources, approved workspaces, and allowed documents.
- Using the Python MCP client, read one real demo ticket and one demo guideline page; save safe evidence of both reads.
- Identify the actual reading tools and their required inputs. Do not assume that a tool exists because its name sounds plausible.
- Confirm sign-in, credential renewal, and what happens when access is revoked. Record any access blocker before dependent work begins.
- Connection setup and reconnect instructions are documented without credentials.

### TCR-004 — Create a small fictional team and repeatable examples

**Depends on:** TCR-001A. **Spec:** §§1, 10–11.

**Description:** Prepare the examples that will explain the product throughout development and provide known outcomes for testing.

**Acceptance criteria**

- Create fictional customer-lookup code, a linked ticket, and a guideline stating when a customer lookup must include the tenant ID.
- Include an unsafe change, a safe change, a necessary related-file lookup, and an unrelated existing defect that should not be reported.
- Include examples for a valid exception, an expired exception, conflicting rules, missing context, and an attempted instruction to bypass reviewer controls.
- Record expected findings, findings that must not appear, and expected limitations. Examples can be reset and rerun.
- All example code and documents are safe to publish and use in the demo.

## Stage 1 — Review a change locally

### TCR-005 — Save review records and validate settings

**Depends on:** TCR-001. **Spec:** §§2–3, 7–9.

**Description:** Give every review a reliable record of what it used, what happened, and what it produced.

**Acceptance criteria**

- Settings and review records use the shared Pydantic formats; invalid or unsupported input is rejected with a useful explanation.
- Save the reviewed code versions, rule/skill/model versions, source references, findings, and limits used for each run.
- Record progress and distinguish complete, partial, failed, superseded, cancelled, and skipped runs, including reasons.
- SQLite records survive a restart. Database updates preserve existing records and reject duplicate identities.
- A rule, model, or source change during a run does not silently change that run’s recorded inputs.

### TCR-006 — Read the exact code change safely

**Depends on:** TCR-004, TCR-005. **Spec:** §§2–4.

**Description:** Load the proposed change with enough detail to place each finding on the correct version and line.

**Acceptance criteria**

- Read additions, deletions, and renamed files between the chosen code versions, preserving old and new line references.
- For PRs, compare against the shared starting point with the target branch so unrelated target-branch changes are excluded.
- Invalid paths, unavailable versions, and unsupported files are reported explicitly; omitted content is never treated as reviewed.
- Reading a repository does not run its code, install its dependencies, or execute its setup instructions.
- Example changes can be loaded through the command line without a running web service.

### TCR-007 — Keep investigation focused and within limits

**Depends on:** TCR-006. **Spec:** §4.

**Description:** Let the reviewer inspect related code only when necessary to answer a specific question about the change.

**Acceptance criteria**

- Every additional read records its question, originating changed code, direct relationship, and expected evidence. Unsupported relationships are rejected.
- Stop reading when the question is answered. Do not explore another repository or report an unrelated existing defect.
- Enforce configurable limits on changed files/lines, extra reads, relationship depth, MCP/model calls, input size, and elapsed time, using the spec’s starting values. Retries count toward those limits.
- Hitting a limit produces a partial review with the omitted scope or unresolved question; nothing is silently dropped.
- Read application tests only for a change-specific question or an approved team requirement. Do not assess coverage, audit test quality, or run application tests.

### TCR-008 — Run the review through a Meta model

**Depends on:** TCR-002, TCR-005. **Spec:** §§3, 7.

**Description:** Connect the shared review process to the selected Meta model without putting provider-specific details into review skills.

**Acceptance criteria**

- The model can request relevant context, return proposed findings, or finish with stated limitations using the agreed response format.
- Implement the model connection as a provider class behind the shared interface; the review service receives it through its constructor.
- The application checks permissions and inputs before carrying out any model request. The model cannot publish, change rules, or call unrestricted tools.
- Invalid responses get at most one repair attempt; continued failure is recorded as a failure, not a successful empty review.
- Timeouts and cancellation stop further work. Model identity, usage when available, and unsupported features are recorded.

### TCR-009 + TCR-010 — Review a change locally with tested skills

**Depends on:** TCR-004, TCR-007, TCR-008. **Spec:** §§3, 7–8, 10.

**Description:** Make review behavior reusable and testable, then turn the bounded Meta review into a local report a developer can understand and act on.

**Acceptance criteria**

- Each skill includes its name/version, instructions, file scope, requested tools, model choice, and acceptable/violating examples with expected results. Only skills matching the changed files run, and their permissions cannot exceed the team’s approved permissions.
- Unknown formats, missing files, changed package contents, unsafe paths, and executable additions are rejected. A new or changed skill must pass its examples for the selected model settings before activation.
- Provide starter skills for correctness, team standards, and ticket intent/completeness. Architecture and compatibility issues fit within these skills.
- Each finding identifies the changed location, severity, problem, consequence, triggering example, supporting evidence, and suggested remedy.
- Check quoted code and source passages, rule applicability, and the connection to the change. A separate review step challenges weak reasoning and existing unrelated problems. An essential unsupported assumption becomes an unresolved question, not an asserted defect; apparent security issues follow the same evidence requirements.
- The command line saves a readable summary and a machine-readable report with findings, reviewed scope, and limitations, without a running web service. Say when tests were not run; never invent reproduction evidence. “Review complete” does not claim the change is proven correct.
- The safe, unsafe, and related-file examples produce their expected outcomes.

## Stage 2 — Understand the team

### TCR-011 + TCR-014 — Retrieve ticket and guideline context safely

**Depends on:** TCR-003, TCR-009 + TCR-010. **Spec:** §§2, 5, 8–9.

**Description:** Supply the reviewer with the reason for the change and the relevant team documentation, without letting that information grant new permissions or leak.

**Acceptance criteria**

- Retrieve explicit ticket links from the PR or a local request, and guideline locations from approved settings, through MCP. Read the source content rather than search previews. Search only within approved workspaces when necessary; ambiguous matches remain unresolved.
- Save the source link, workspace, relevant passage, content fingerprint, retrieval time, and source version when provided. Do not invent a version.
- Distinguish missing links, denied or expired access, rate limits, incomplete content, and conflicting sources in the result. A review never waits for someone to sign in.
- Use only approved read tools, workspaces, and documents. A tool calling itself “read-only” is not enough to approve it. Reject requests that escape approved locations, follow unapproved redirects, or send source code to an unrelated service.
- Code, tickets, and wiki text cannot change permissions, model settings, rules, or publication destinations.
- Credentials and unnecessary source contents do not appear in prompts, logs, or reports. Private passages are published only when the team has approved disclosure to that repository; otherwise they are redacted or the limitation is explained. Later PR comments and replies use the same check.
- Tests demonstrate blocked bypass attempts, including the fictional bypass example, and private-source protection.

### TCR-012 + TCR-013 — Apply approved standards and exceptions

**Depends on:** TCR-011 + TCR-014. **Spec:** §§5–6.

**Description:** Make team rules predictable, prevent a proposed change from rewriting the standards used to review itself, and allow documented, limited departures from a rule.

**Acceptance criteria**

- Load rules and skill permissions from the approved version, not from changes inside the PR being reviewed. Tickets explain intended behavior but cannot silently become team policy or override tool permissions.
- Apply rules only to their intended repository, service, path, or file type. Record their source, rationale, owner, and approval.
- A narrower rule can replace a broader one only when explicitly allowed and identified. Otherwise report the conflict and leave the affected check incomplete.
- Detect changes to approved wiki passages. New text needs approval; older approved text may be used only when the team permits it, with that choice disclosed. Otherwise report the missing current policy.
- An exception names the exact rule/version, allowed condition, scope, reason, owner, approver, and optional expiry. Only an authorized approval makes it active; it cannot waive a rule that forbids exceptions or expand reviewer permissions.
- A valid matching exception suppresses only that rule violation; independent correctness problems remain reviewable. Expired, out-of-scope, or outdated-rule exceptions do not suppress findings.
- The review record explains which exception applied and why. The valid-exception, expired-exception, and conflicting-rule examples produce their expected outcomes.

## Stage 3 — Review on GitHub

### TCR-015 + TCR-016 — Start reviews from GitHub PRs on the local service

**Depends on:** TCR-009 + TCR-010. **Spec:** §§2–3, 9.

**Description:** Run the FastAPI service locally so trusted GitHub PR events start reviews of the exact PR change. There is no hosted deployment.

**Acceptance criteria**

- Configure a GitHub App for the demo repository with reading, commenting, and check permissions only, without merge or repository-administration access. Document how events reach the locally running service without committing the app key or webhook secret.
- Verify event authenticity before processing. Reject unexpected repositories or event types, and ignore repeated deliveries and bot loops.
- Fetch the PR’s head and target commits into a local repository and review them with the existing change reader. Never check out or run PR code.
- Save accepted work before acknowledging receipt. Restarting the local service recovers unfinished jobs without launching duplicate work for the same PR.
- Review an eligible PR automatically when it opens and when new commits arrive. A collaborator with write access can request a rerun by command; check the sender’s current permission rather than an identity written in the command. A skipped review says why.
- Job progress and failure reasons are visible without exposing secrets.

### TCR-017 + TCR-018 + TCR-019 — Publish, update, and report reviews on the PR

**Depends on:** TCR-012 + TCR-013, TCR-015 + TCR-016. **Spec:** §§3, 8–9.

**Description:** Present one understandable, current review on the PR, update it safely after new commits, and say plainly whether the review found a problem, could not finish, or failed.

**Acceptance criteria**

- Maintain one summary and place findings on the correct changed lines, including deleted lines. If inline placement is impossible, use the summary with exact references.
- Each finding has a lasting identity. Repeated runs update existing findings rather than duplicating unchanged comments, and human replies are preserved.
- Save planned publications and check whether a comment already appeared before retrying after an uncertain response.
- Later runs inspect newly changed code, affected earlier findings, and directly affected recorded dependencies. Reuse previous results only when their code, rules, skills, model settings, and source contents are unchanged; otherwise, or after a changed shared starting point or an incomplete previous run, review the full PR again.
- Resolve a finding only after checking it again. If a newer commit arrives, stop outdated publication; only the current version receives the current outcome.
- An advisory GitHub check and the summary report findings separately from missing context, exhausted limits, conflicting policy, execution errors, and publication failures. An incomplete review is never reported as passing. The reviewer never changes merge-protection settings.

## Stage 4 — Explain and learn

### TCR-020 + TCR-021 — Explain and reassess findings

**Depends on:** TCR-017 + TCR-018 + TCR-019. **Spec:** §§8, 10.

**Description:** Make findings understandable without weakening their substance, and give developers a way to correct the reviewer.

**Acceptance criteria**

- In a review thread, people can ask for simpler wording, more technical detail, a concrete failure example, evidence, or the connection to their change.
- Technical complexity and verbosity are separate settings with a team default and a per-request override.
- Rewording preserves severity, rule, evidence, limitations, and conclusion. Even a short answer explains the problem, link to the change, and consequence. Replies honor access/disclosure rules and use the Meta model.
- A person can accept, dismiss, or challenge a finding, with a reason where needed; record the actor and event.
- A challenge starts a bounded reassessment of the existing evidence and any necessary additional context. Amend or withdraw an unsupported finding with an explanation, preserving its history; never defend it with invented evidence.
- Acceptance or dismissal does not automatically create a team rule, and a dismissal is not counted as proof that the finding was wrong.

### TCR-022 + TCR-023 — Propose, test, and approve team learning

**Depends on:** TCR-012 + TCR-013, TCR-020 + TCR-021. **Spec:** §6.

**Description:** Capture reusable team knowledge as an explicit, tested team decision, without letting an ordinary comment change future reviews.

**Acceptance criteria**

- An explicit learning request creates an inactive proposal containing the exact rule text, source discussion, rationale, owner, scope, and examples. It cannot expand tool or publication permissions.
- Test the proposal against the affected skill’s acceptable and violating examples, and record the rule version, skill/model settings, and results. A failed or incomplete evaluation prevents approval; editing the proposal invalidates the earlier evaluation until it is rerun.
- A person can inspect the exact proposal and its evidence before approval.
- Only a designated, currently authorized approver can approve the exact tested proposal. Reject approval of an older or changed version; repeating an approval does not create duplicate active rules.
- Approval creates a recorded active rule version for future runs; old review records remain unchanged. Approved learning follows the same scope, conflict, and exception rules as other standards, with no hidden higher priority.

## Stage 5 — Prove the MVP locally

These tickets test the assembled product running locally through Docker Compose, not isolated functions. Keep the example inputs, reviewed version, configuration, actual result, and evidence link together. A failed outcome remains visible until fixed and retested.

### TCR-028 + TCR-031 — Verify the PR review journey locally

**Depends on:** TCR-022 + TCR-023. **Spec checks:** A01–A04, A12, A14.

**Description:** Prove the main user journey on a real PR in the demo repository, with the service running locally, live team context, and the Meta model, and show that repeated events and restarts do not create misleading or duplicate reviews.

**Acceptance criteria**

- Open the unsafe example PR with its linked ticket. The reviewer retrieves the ticket and approved guideline through live MCP and publishes the expected finding, citing changed code and relevant source passages, explaining the failure, and suggesting a remedy.
- Any related-file inspection has a recorded reason and direct relationship. The unrelated existing defect is not reported; no general test audit or application-test execution occurs. The safe example has no expected violation.
- Push a fix and verify the finding is rechecked and resolved without duplicate comments.
- Repeat the same event and rerun command; unchanged findings are not duplicated. Interrupt publication after a comment reaches GitHub, then retry; the existing comment is found and reused.
- Push another commit during a review; old results are not reported for newer code. Restart the local service with queued and active work; jobs recover and incomplete runs do not become successful.
- Save evidence of the initial result, necessary context reads, corrected result, and recovery checks.

### TCR-029 + TCR-030 — Verify team control, honesty, and safety locally

**Depends on:** TCR-022 + TCR-023. **Spec checks:** A05–A11, A14–A16.

**Description:** Prove that the team can understand, correct, and teach the reviewer, and that it stays honest and controlled when information is missing or tries to mislead it.

**Acceptance criteria**

- Try all combinations of complexity and verbosity; the stored severity, evidence, limitations, and conclusion are unchanged by wording requests.
- Challenge an intentionally unsupported finding and verify it is reassessed and withdrawn with an explanation.
- Show a proposed learning has no effect before testing and approval, then changes a later review after authorized approval. Reject an unauthorized approver and an approval for an outdated proposal.
- A valid exception suppresses only its intended violation; an expired or outdated-rule exception does not.
- Denied, missing, conflicting, or over-budget context is reported, and a changed wiki rule or conflicting standard is exposed; no facts or passing outcome are invented. Unsupported cross-service claims remain unresolved questions.
- Attempts inside a PR, ticket, or wiki to change permissions, approved rules, model settings, or destinations are blocked, and an unauthorized rerun command is refused. Private-source content is not leaked into a finding, reply, report, or log.

### TCR-024 + TCR-032 — Compare Meta models and prepare the local demo

**Depends on:** TCR-028 + TCR-031, TCR-029 + TCR-030. **Spec:** §§7, 10–11; **spec check:** A13.

**Description:** Compare the selected Meta models through the shared interface, record reproducible evidence of what works and what remains limited, and prepare a demo that runs locally. Other providers are deferred for this hackathon.

**Acceptance criteria**

- The same versioned skills and examples run against the selected Meta models through the shared interface. A skill selects its configured model without rewriting its instructions; unsupported features and invalid responses produce explicit limitations or failures, with no hidden fallback.
- Run the agreed example suite three times per selected model configuration. Record expected versus actual findings, missed issues, incorrect findings, response failures, elapsed time, and available usage. Do not claim identical output or general accuracy from a small example set.
- Permission, approval, change-attribution, and duplicate-publication checks pass every time. Fix and rerun failures; do not hide them in averages.
- Someone who did not build rush can follow the documentation to run it locally: Docker Compose, Meta credentials, MCP connection, the GitHub App and local event forwarding, and approved rules.
- Complete the coverage table below with evidence links. Distinguish automated example results from human acceptance/dismissal feedback.
- Prepare a three-minute demo, run locally, showing live-context review, a necessary dependency read, clarification, a valid exception, approved learning, second-model results, and an honest missing-context result. Label prerecorded output clearly.
- Check the repository and video for accidental private content before sharing them, and verify access and contributor details. Record remaining limitations; unfinished MVP requirements are not marked Done.

## Removed from the MVP

Removed by the owner on 30 October 2026 because the demo does not need them. The
IDs stay retired and are not reused.

- **TCR-025 — Run the reviewer locally and in CI.** Local command-line review is
  delivered by TCR-009 + TCR-010. CI review mode and exporting approved rules for
  other environments are out.
- **TCR-026 — Recover from failures and manage stored information.** Restart
  recovery is in TCR-015 + TCR-016, and budgets and model retries are in TCR-007
  and TCR-008. Excerpt retention, backup/restore, export/deletion, and extra
  spending controls are out.
- **TCR-027 — Deploy the MVP and document a fresh setup.** There is no hosted
  deployment. Local setup documentation moves to TCR-024 + TCR-032.

Also removed from tickets that remain:

- Required merge-check mode (TCR-019); outcomes are advisory only.
- Draft, label, file-path, and pause/resume review controls (TCR-016).
- Saved personal explanation preferences (TCR-020).
- Retiring, expiring, and exporting team learning (TCR-023).
- Linking replacement comments when a finding moves, and branch-history rewrite
  tests (TCR-017, TCR-031).

## Repository support tasks

### TCR-033 — Preserve project knowledge across agent sessions

**Owner update, 30 October 2026:** The `knowledge/` folder is internal and
local-only, excluded from Git and Docker images. Hooks and CI validate it when
present; fresh clones use tracked project docs. Do not reintroduce it to Git.

**Type:** Task. **Depends on:** TCR-001. **Priority:** owner-requested before
resuming TCR-002. This supports development; it adds no product review feature.

**Description:** Use the supplied LLM Wiki pattern and Open Knowledge Format to
keep project context in the repository so another session can resume without a
pasted handover. TCR-002 stays paused until this task's PR is reviewed and merged.

**Acceptance criteria**

- Seed a linked wiki with project purpose, architecture, working agreements,
  decisions, completed setup, current work, blockers, and evidence.
- Use OKF metadata and source references. Mark unknowns; do not invent model
  identity, live access, approvals, or billing/data settings.
- Instruct agents to read the starting pages, check live Git/PR state, and update
  the wiki before stopping or handing off. Preserve the review reply rules.
- Provide Docker commands for validation and a starting context. Check required
  project metadata, navigation, local source drift, and invalid links, with
  behavior tests for failures. Run validation in hooks and required CI.
- Verify the exported checkout works without chat history or private accounts.
  Include safe source records; exclude credentials and private transcripts.
- Open a focused PR, wait for human review/merge, then return to TCR-002.

**Sources:** [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
[Google introduction](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing),
and [canonical OKF specification](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md).

## Coverage and final sign-off

The IDs below are the acceptance scenarios in the technical spec. Implementation tickets explain what to build; verification tickets prove the behavior in the assembled MVP running locally.

| Spec check | Behavior | Implementation tickets | Final verification |
|---|---|---|---|
| A01 | Evidence-backed violation tied to the change | TCR-006, 008–010, 012, 017 | TCR-028 + 031 |
| A02 | Safe change; ignore unrelated problems | TCR-007, 010 | TCR-028 + 031 |
| A03 | Necessary related-file inspection | TCR-007 | TCR-028 + 031 |
| A04 | Live ticket and approved guideline retrieval | TCR-003, 011–012 | TCR-028 + 031 |
| A05 | Explicit missing-context and budget limits | TCR-007–008, 011, 019 | TCR-029 + 030 |
| A06 | Reject unapproved rule/permission changes | TCR-006, 009, 012, 014 | TCR-029 + 030 |
| A07 | Respect valid exceptions, reject expired ones | TCR-013 | TCR-029 + 030 |
| A08 | Expose policy conflict or changed wiki text | TCR-012 | TCR-029 + 030 |
| A09 | Learning changes behavior only after approval | TCR-022–023 | TCR-029 + 030 |
| A10 | Reject unauthorized/stale approvals | TCR-023 | TCR-029 + 030 |
| A11 | Clear explanations and supported reassessment | TCR-020–021 | TCR-029 + 030 |
| A12 | No duplicates or outdated results | TCR-015, 017–018 | TCR-028 + 031 |
| A13 | Same skills through selected Meta models; replaceable provider boundary | TCR-002, 009, 024 | TCR-024 + 032 |
| A14 | No unsolicited application-test assessment | TCR-007, 010 | TCR-028 + 031, TCR-029 + 030 |
| A15 | Incomplete review is never reported as passing (advisory only; required-check mode removed) | TCR-019 | TCR-029 + 030 |
| A16 | Private-source disclosure is controlled | TCR-014, 020 | TCR-029 + 030 |

**MVP sign-off:** the implementation tickets are accepted, the local end-to-end tickets pass, and TCR-024 + TCR-032 links the final evidence. Setup/access decisions still open in the technical spec are resolved through TCR-001–003; this document does not assume those accounts or connections already work.

**Setup sign-off:** TCR-001A–001E provide evidence that the requested layout, OOP/provider boundaries, meaningful testing, backend CI/coverage/quality merge gate, and safe development practices are implemented. The original MVP had 32 parent tickets plus five setup subtasks; TCR-033 is an additional repository support task. On 30 October 2026, TCR-025–027 were removed and the remaining 21 tickets were merged into ten work items.

**Verification basis:** all 12 PRD requirement areas and all 16 technical-spec acceptance scenarios were checked when preparing this backlog. A15 is narrowed to advisory outcomes by the 30 October scope update; the other 15 scenarios are unchanged. Ticket wording, grouping, and dependencies are planning decisions derived from the spec; acceptance criteria describe intended behavior, not completed work. The coverage table is the starting point for the development record.
