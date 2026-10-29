# rush — MVP Requirements and Tickets

Version 1.2 · 28 October 2026 · rush naming and Docker workflow

**Source:** [Technical Specification v0.4 — Python/FastAPI](technical-spec.md), paired with `docs/development-guide.md`. This backlog turns the agreed design into implementation and testing tasks. It does not mark any development work as completed or create tasks in ClickUp.

**Working decisions:** use `rush` for the application and CLI; preserve TCR IDs.
Use Docker Compose for running, testing, and development tools, with no host venv.
Finish each ticket, open its PR, and wait for human review and merging before
starting the next one. TCR-001A–001E are subtasks delivered in the TCR-001 parent PR.

**Development versus product behavior:** the playbook guides how we develop this backend. Our own repository must pass meaningful tests, coverage and quality checks. Those checks do not become coverage-audit or security-scanning features in the reviewer. The required FastAPI layout, class-based services, and provider pattern apply to every implementation ticket below.

## How to use this backlog

Each numbered heading is a ticket title. Copy its description and acceptance criteria into ClickUp, keep its ID, and use the stage as its group. “Depends on” identifies work needed before the ticket can be accepted; start another ticket only after the current ticket PR has been reviewed and merged.

**Default fields:** Status = To do; Assignee = Unassigned; Scope = Required for MVP. Assign owners and dates when work is scheduled. The order shows dependencies, not a promise that every ticket takes the same effort.

**Suggested statuses:** To do → In progress → Ready to verify → Done; use Blocked when a dependency or access problem prevents progress.

**Done means:** all acceptance criteria have been checked, relevant tests pass, and changed setup or behavior is documented. Add one short completion note: **what changed; evidence link; any remaining limitation**. Use a test result, example review, or screenshot as evidence where useful. Do not mark work Done on the strength of a code change alone.

Every implementation ticket also follows the development guide: business logic stays in service classes; outside calls use injected provider/repository interfaces; tests guard behavior and regressions rather than framework internals or a target percentage; the required backend CI gate passes. TCR-001 now has five setup subtasks, TCR-001A–001E. Existing ticket IDs remain unchanged. Complete the setup parent and wait for its PR to be reviewed and merged before starting model/context access experiments or fictional-example work under later tickets.

**Terms:** A PR is a proposed code change on GitHub. A review skill is a reusable set of review instructions with examples that check it works. MCP is the connection used to read tickets and team documents.

## The development story

| Stage | Tickets | What should work by the end |
|---|---|---|
| 0. Set up and prove access | TCR-001–004, including TCR-001A–001E | Required layout, OOP boundaries, meaningful tests, secure configuration, and an actual backend merge gate are established; models/context and demo examples are ready. |
| 1. Review a change locally | TCR-005–010 | A local review finds supported issues and explains its limits. |
| 2. Understand the team | TCR-011–014 | Reviews use relevant tickets, approved standards, and valid exceptions without exposing private information. |
| 3. Review on GitHub | TCR-015–019 | Reviews start, update, and report their outcome reliably on real PRs. |
| 4. Explain and learn | TCR-020–023 | People can question findings, adjust explanations, and approve learning. |
| 5. Make it portable and dependable | TCR-024–026 | The reviewer works with another model, in local/CI use, and through common failures. |
| 6. Prove the complete MVP | TCR-027–032 | Someone else can set it up; full workflows pass; evidence and a demo are ready. |

**Scope stays small:** one repository, one team, two model connections, and a small skill set. Demonstrate one ticket source and one approved guideline source through live MCP connections. ClickUp tickets plus Notion guidelines is the preferred setup; ClickUp tasks plus Docs is an allowed alternative.

**Outside this MVP:** a custom dashboard, marketplace, extra integrations, broad repository exploration, dedicated security scanning, coverage checks, general test-quality reviews, running the application’s tests, code generation, automatic fixes/merges, and post-merge work. Tests of the reviewer itself are required. Apparent security issues may still be reported when supported by the changed code.

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

### TCR-002 — Confirm access to both model providers

**Depends on:** TCR-001A. **Spec:** §§7, 13.

**Description:** Resolve account and model-access risks before building the review workflow around them.

**Acceptance criteria**

- A small request succeeds through the chosen Meta model and through a separate model provider from Python.
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

### TCR-009 — Load reusable review skills and check their examples

**Depends on:** TCR-004, TCR-005, TCR-008. **Spec:** §§7, 10.

**Description:** Make review behavior reusable, versioned, and testable before a skill is enabled.

**Acceptance criteria**

- Each skill includes its name/version, instructions, file scope, requested tools, model choice, and acceptable/violating examples with expected results.
- Only skills matching the changed files run. Their permissions cannot exceed the team’s approved permissions.
- Unknown formats, missing files, changed package contents, unsafe paths, and executable additions are rejected.
- A new or changed skill must pass its examples for the selected model settings before activation.
- Provide starter skills for correctness, team standards, and ticket intent/completeness. Architecture and compatibility issues fit within these skills.

### TCR-010 — Produce useful findings and a local review report

**Depends on:** TCR-007, TCR-008, TCR-009. **Spec:** §§3, 8.

**Description:** Turn proposed findings into a review a developer can understand and act on.

**Acceptance criteria**

- Each finding identifies the changed location, severity, problem, consequence, triggering example, supporting evidence, and suggested remedy.
- Check quoted code and source passages, rule applicability, and the connection to the change. A separate review step challenges weak reasoning and existing unrelated problems.
- An essential unsupported assumption becomes an unresolved question, not an asserted defect. Apparent security issues follow the same evidence requirements.
- Save a readable summary and a machine-readable report with findings, reviewed scope, and limitations. Say when tests were not run; never invent reproduction evidence.
- Safe and unsafe local examples produce their expected outcomes. “Review complete” does not claim the change is proven correct.

## Stage 2 — Understand the team

### TCR-011 — Retrieve relevant ticket and wiki context during a review

**Depends on:** TCR-003, TCR-005, TCR-007. **Spec:** §5.

**Description:** Supply the reviewer with the reason for the change and the relevant team documentation.

**Acceptance criteria**

- Retrieve explicit ticket links from the PR or an authorized request, and guideline locations from approved settings, through MCP.
- Read the source content rather than relying on search previews. Search only within approved workspaces when necessary; ambiguous matches remain unresolved.
- Save the source link, workspace, relevant passage, content fingerprint, retrieval time, and source version when provided. Do not invent a version.
- Distinguish missing links, denied access, rate limits, incomplete content, and conflicting sources in the result.
- Renew access where supported; failed renewal requests reconnection without leaving an unattended review waiting for sign-in.

### TCR-012 — Apply only approved team standards

**Depends on:** TCR-005, TCR-009, TCR-011. **Spec:** §§5–6.

**Description:** Make team rules predictable and prevent a proposed change from rewriting the standards used to review itself.

**Acceptance criteria**

- Load rules and skill permissions from the approved version, not from changes inside the PR being reviewed.
- Apply rules only to their intended repository, service, path, or file type. Record their source, rationale, owner, and approval.
- A narrower rule can replace a broader one only when explicitly allowed and identified. Otherwise report the conflict and leave the affected check incomplete.
- Tickets explain intended behavior but cannot silently become team policy or override tool permissions.
- Detect changes to approved wiki passages. New text needs approval; older approved text may be used only when the team permits it, with that choice disclosed. Otherwise report the missing current policy.

### TCR-013 — Respect approved exceptions

**Depends on:** TCR-012. **Spec:** §6.

**Description:** Allow documented, limited departures from a rule without weakening the rest of the review.

**Acceptance criteria**

- An exception names the exact rule/version, allowed condition, scope, reason, owner, approver, and optional expiry.
- Only an authorized approval makes it active. It cannot waive a rule that forbids exceptions or expand reviewer permissions.
- A valid matching exception suppresses only that rule violation; independent correctness problems remain reviewable.
- Expired, retired, out-of-scope, or outdated-rule exceptions do not suppress findings. Rule changes require exception reapproval.
- The review record explains which exception applied and why.

### TCR-014 — Protect tool access and private context

**Depends on:** TCR-007, TCR-011, TCR-012. **Spec:** §§2, 5, 8–9.

**Description:** Ensure that reading team information never grants permission to change it or publish it elsewhere.

**Acceptance criteria**

- Only approved read tools, workspaces, documents, and destinations can be used. A tool calling itself “read-only” is not enough to approve it.
- Code, tickets, and wiki text cannot change permissions, model settings, rules, or publication destinations.
- Reject requests that escape approved locations, follow unapproved redirects, or send source code to an unrelated service.
- Publish private passages only when the team has approved disclosure to that repository; otherwise redact or explain the limitation. Apply this to replies as well as initial findings.
- Credentials and unnecessary source contents do not appear in prompts, logs, reports, or public comments. Tests demonstrate blocked bypass attempts and private-source protection.

## Stage 3 — Review on GitHub

### TCR-015 — Receive GitHub events and save work reliably

**Depends on:** TCR-001, TCR-005. **Spec:** §§2–3, 9.

**Description:** Build the FastAPI service that accepts trusted GitHub events and processes saved review work.

**Acceptance criteria**

- Configure the GitHub App with the required reading, commenting, and check permissions, without merge or repository-administration access.
- Verify event authenticity before processing; reject unexpected repositories or event types and ignore repeated deliveries and bot loops.
- Save accepted work before acknowledging receipt. A restart recovers unfinished jobs without launching duplicate work for the same PR.
- Run the agreed single service process and review worker. Startup opens required connections; shutdown stops safely and closes them.
- Job progress and reasons for failure are visible without exposing secrets. A failed worker is detected rather than leaving jobs silently stuck.

### TCR-016 — Control when reviews run

**Depends on:** TCR-010, TCR-015. **Spec:** §§3, 8–9.

**Description:** Support automatic review and clear commands while giving the team control over eligibility and usage.

**Acceptance criteria**

- Start eligible PR reviews automatically and allow an authorized person to request a full review or rerun.
- Honor target branch, draft, label, file-path, and pause settings; explain why a review was skipped.
- Maintainers can pause/resume reviews. Billable commands are restricted to configured collaborators, not any public commenter.
- Check the real sender’s current permissions; do not trust an identity written inside a command.
- Changes to eligibility are re-evaluated, and resuming schedules the current eligible version rather than reviving stale work.

### TCR-017 — Publish findings without duplicate comments

**Depends on:** TCR-010, TCR-014, TCR-016. **Spec:** §8.

**Description:** Present one understandable, current review on the PR while preserving the conversation around each finding.

**Acceptance criteria**

- Maintain one summary and place findings on the correct changed lines, including deleted lines. If inline placement is impossible, use the summary with exact references.
- Each finding has a lasting identity. Repeated runs update existing findings rather than duplicating unchanged comments.
- Preserve human replies. When a moved location requires a replacement comment, clearly link it to the previous finding.
- Save planned publications and check whether a comment already appeared before retrying after an uncertain response.
- Publication failures remain distinguishable from review failures and prevent a false claim that the result was fully delivered.

### TCR-018 — Update reviews safely after new commits

**Depends on:** TCR-017. **Spec:** §3.

**Description:** Focus repeat reviews on new changes without losing old findings or publishing results against outdated code.

**Acceptance criteria**

- The first run reviews the full PR; later runs inspect newly changed code, affected earlier findings, and directly affected recorded dependencies.
- Reuse previous results only when their relevant code, rules, skills, model settings, and required source contents are unchanged.
- Restart with a full review after incompatible history changes, a changed shared starting point, changed review inputs, or an incomplete previous run.
- Resolve a finding only after checking it again. Unchecked findings remain open or marked for rechecking, not silently closed.
- If a newer commit arrives, stop outdated publication and identify any already-published old result. Only the current version may receive the current review outcome.

### TCR-019 — Report advisory and required review outcomes honestly

**Depends on:** TCR-013, TCR-017, TCR-018. **Spec:** §9.

**Description:** Make it clear whether a review found a problem, could not finish, or failed to run.

**Acceptance criteria**

- Reviews are advisory by default. A maintainer explicitly enables a separate required check and selects the severity threshold.
- A complete review reports findings separately from missing context, exhausted limits, conflicting policy, and execution errors.
- A required check cannot pass when required review work is missing, paused, unsupported, or incomplete. A superseded run cannot pass for newer code.
- A change with no applicable required work passes only after that absence is confirmed and explained.
- The reviewer never changes GitHub’s merge-protection settings automatically. Test the outcome combinations listed in the spec.

## Stage 4 — Explain and learn

### TCR-020 — Let people adjust and question explanations

**Depends on:** TCR-017. **Spec:** §8.

**Description:** Make findings understandable without weakening their substance.

**Acceptance criteria**

- In a review thread, people can ask for simpler wording, more technical detail, a concrete failure example, evidence, or the connection to their change.
- Technical complexity and verbosity have separate settings, with team defaults, saved personal preferences, and per-request overrides.
- A request overrides personal preferences; personal preferences override team defaults. Settings apply to the identified user.
- Rewording preserves severity, rule, evidence, limitations, and conclusion. Even a short answer explains the problem, link to the change, and consequence.
- Replies honor access/disclosure rules and use the Meta model in the main demo.

### TCR-021 — Reassess challenged findings and record feedback

**Depends on:** TCR-020. **Spec:** §§8, 10.

**Description:** Give developers a way to correct the reviewer and make its response visible.

**Acceptance criteria**

- A person can accept, dismiss, or challenge a finding, with a reason where needed; record the actor and event.
- A challenge starts a bounded reassessment of the existing evidence and any necessary additional context.
- Amend or withdraw an unsupported finding with an explanation, preserving its history. Do not defend it using invented evidence.
- Acceptance or dismissal does not automatically create a team rule. A dismissal is not automatically counted as proof that the finding was wrong.

### TCR-022 — Turn feedback into a tested learning proposal

**Depends on:** TCR-009, TCR-012, TCR-021. **Spec:** §6.

**Description:** Capture reusable team knowledge without letting an ordinary comment change future reviews.

**Acceptance criteria**

- An explicit learning request creates a proposal containing the exact rule text, source discussion, rationale, owner, scope, and examples.
- Proposed learning remains inactive and cannot expand tool or publication permissions.
- Test the proposal against the affected skill’s acceptable and violating examples, and record the rule version, skill/model settings, and results.
- A failed or incomplete evaluation prevents approval. Editing the proposal invalidates the earlier evaluation until it is rerun.
- A person can inspect the exact proposal and its evidence before approval.

### TCR-023 — Approve, change, and retire team learning

**Depends on:** TCR-013, TCR-022. **Spec:** §6.

**Description:** Make learning an explicit team decision with a clear history and a way to remove it.

**Acceptance criteria**

- Only a designated, currently authorized approver can approve the exact tested proposal. Reject approval of an older or changed version.
- Approval creates a recorded active rule version for future runs. A rerun uses that version; old review records remain unchanged.
- Edited learning requires fresh testing and approval. Retirement or expiry stops it applying to later reviews and records the reason.
- Approved learning follows the same scope, conflict, and exception rules as other standards; it has no hidden higher priority.
- Repeating an approval does not create duplicate active rules. Approved rules can be exported for local and CI use without automatically committing to the repository.

## Stage 5 — Make it portable and dependable

### TCR-024 — Support the second model and compare review results

**Depends on:** TCR-002, TCR-009, TCR-010. **Spec:** §§7, 10.

**Description:** Demonstrate model choice with a working second connection, not just a configuration option.

**Acceptance criteria**

- The same versioned skill and examples run against the Meta model and the second real provider using the shared response format.
- Supply the second provider through the same interface; changing provider does not require changing the service’s business logic.
- A skill can select its configured model without rewriting its instructions or embedding provider-specific code.
- Unsupported features and invalid responses produce explicit limitations or failures; there is no hidden provider fallback.
- Compare actual detected, missed, and incorrect findings, response failures, elapsed time, and available usage data. Do not claim identical output or general accuracy from a small example set.

### TCR-025 — Run the reviewer locally and in CI

**Depends on:** TCR-010, TCR-023, TCR-024. **Spec:** §§2, 9.

**Description:** Let a team run the reviewer with its own settings and credentials outside the hosted GitHub service.

**Acceptance criteria**

- Document working local and CI commands using the same review logic, an explicit code range, and an approved rules package.
- Both modes produce readable and machine-readable results. Publishing is separately enabled; local review does not require a running web service.
- Exported approved learning and skill versions can be loaded in a fresh environment. Missing service history is disclosed; no automatic memory sharing is implied.
- A PR cannot substitute its own rules or startup code for the trusted configuration. Example CI setup keeps secrets away from untrusted code execution.

### TCR-026 — Recover from failures and manage stored information

**Depends on:** TCR-005, TCR-008, TCR-011, TCR-015, TCR-017. **Spec:** §9.

**Description:** Make the MVP usable through restarts, outages, and limited budgets, with enough information to troubleshoot it.

**Acceptance criteria**

- Retry temporary connection failures within configured limits. Stop on invalid credentials or permissions, and preserve completed evidence.
- Recovery after restart does not lose accepted jobs, activate rules twice, or duplicate published findings.
- Show run progress, failure reasons, context-read reasons, usage, and limits without storing secrets or unnecessary source content. Unknown cost remains unknown.
- Apply the agreed seven-day default for temporary excerpts; raw model responses are off by default. Keep approved rule evidence separately and mark older reviews when supporting evidence has been removed.
- Provide and verify backup, restore, export, and deletion instructions. Check that stored records survive an upgrade and restoration.
- Enforce spending/request controls in the reviewer; do not present a provider notification as a guaranteed spending cap.

## Stage 6 — Prove the complete MVP

These tickets test the assembled product, not isolated functions. Keep the example inputs, reviewed version, configuration, actual result, and evidence link together. A failed outcome remains visible until fixed and retested.

### TCR-027 — Deploy the MVP and document a fresh setup

**Depends on:** TCR-019, TCR-023, TCR-025, TCR-026. **Spec:** §§2, 9, 11.

**Description:** Make the reviewer accessible and reproducible for someone who did not build it.

**Acceptance criteria**

- Deploy the single-service setup with persistent storage, working GitHub/MCP callbacks, protected credentials, and a reachable health check.
- A fresh setup follows the documentation successfully, including provider credentials, connector authorization, GitHub permissions, and approved rules.
- Document review commands, explanation settings, learning approval, exceptions, skill installation/evaluation, recovery, and current limitations.
- Confirm the development guide, required layout, and backend merge gate still match the deployed source; CI coverage applies to our backend, not to the product’s review output.
- Publish the source and chosen license with safe example settings and demo data; check for accidental private content before publication.
- Restart the deployed service and verify it continues using the same state and approved configuration.

### TCR-028 — Test a complete review from PR to corrected code

**Depends on:** TCR-027. **Spec checks:** A01–A04, A14.

**Description:** Prove the main user journey with a real PR, live team context, and the Meta model.

**Acceptance criteria**

- Open the unsafe example PR with its linked ticket. The reviewer retrieves the ticket and approved guideline through live MCP and publishes the expected finding.
- The finding cites changed code and relevant source passages, explains the failure, and suggests a remedy.
- Any related-file inspection has a recorded reason and direct relationship. The unrelated existing defect is not reported; no general test audit or application-test execution occurs.
- Push a fix and verify the finding is rechecked and resolved without duplicate comments. The safe example has no expected violation.
- Save evidence of the initial result, necessary context reads, and corrected result.

### TCR-029 — Test human clarification, exceptions, and learning

**Depends on:** TCR-027. **Spec checks:** A07, A09–A11.

**Description:** Prove that the team can understand, correct, and teach the reviewer while retaining control.

**Acceptance criteria**

- Try all combinations of complexity and verbosity; the stored severity, evidence, limitations, and conclusion remain unchanged by wording requests.
- Challenge an intentionally unsupported finding and verify it is reassessed and withdrawn with an explanation.
- Show a proposed learning has no effect before testing and approval, then changes a later review after authorized approval.
- Reject an unauthorized approver and an approval for an outdated proposal. Edited, retired, or expired learning behaves as documented.
- A valid exception suppresses only its intended violation; an expired or outdated-rule exception does not.

### TCR-030 — Test missing information, privacy, and permission boundaries

**Depends on:** TCR-027. **Spec checks:** A05–A06, A08, A14–A16.

**Description:** Prove that the reviewer remains honest and controlled when information is missing or tries to mislead it.

**Acceptance criteria**

- Denied, missing, truncated, conflicting, or over-budget context is reported; no facts or clean required-check pass are invented.
- A changed wiki rule or conflicting standard is exposed without silently enforcing unapproved text.
- Attempts inside a PR, ticket, or wiki to change permissions, approved rules, model settings, or destinations are blocked.
- Private-source content is not leaked into a public finding, clarification reply, report, or log. Approved disclosures work as configured.
- Unsupported cross-service claims remain unresolved questions. Application tests are neither run nor generally audited.
- Required checks distinguish incomplete work from execution failure and cannot pass for either case.

### TCR-031 — Test updates, retries, and restarts on real PRs

**Depends on:** TCR-027. **Spec checks:** A12, A15.

**Description:** Prove that event timing and repeated work do not create misleading or duplicate reviews.

**Acceptance criteria**

- Repeat the same event and command; unchanged findings and approvals are not duplicated.
- Interrupt publication after a comment reaches GitHub, then retry; the existing comment is found and reused.
- Push another commit during review/publication and rewrite branch history. Old results do not pass for newer code; required full reviews restart correctly.
- Verify that changed rules, models, skills, or required context invalidate affected reused results; unchecked findings are not silently resolved.
- Restart with queued work and active work. Jobs recover, previous state remains, and incomplete runs do not become successful.
- Exercise filters, pause/resume, and unauthorized commands; recorded results match the intended behavior.

### TCR-032 — Record final results and prepare the MVP demonstration

**Depends on:** TCR-024, TCR-028, TCR-029, TCR-030, TCR-031. **Spec:** §§10–11.

**Description:** Close the development story with reproducible evidence of what works, what remains limited, and what was built.

**Acceptance criteria**

- Run the agreed example suite three times per selected model configuration. Record expected versus actual findings, missed issues, incorrect findings, and failures with the tested versions.
- Permission, approval, change-attribution, and duplicate-publication checks pass every time. Fix and rerun failures; do not hide them in averages.
- Complete the coverage table below with evidence links. Distinguish automated example results from human acceptance/dismissal feedback.
- Prepare a three-minute demo showing live-context review, a necessary dependency read, clarification, a valid exception, approved learning, second-model results, and an honest missing-context result. Label prerecorded output clearly.
- Verify repository/video access and contributor details. Record remaining limitations and any approved scope change in the release notes; unfinished MVP requirements are not marked Done.

## Coverage and final sign-off

The IDs below are the acceptance scenarios in the technical spec. Implementation tickets explain what to build; verification tickets prove the behavior in the assembled MVP.

| Spec check | Behavior | Implementation tickets | Final verification |
|---|---|---|---|
| A01 | Evidence-backed violation tied to the change | TCR-006, 008–010, 012, 017 | TCR-028 |
| A02 | Safe change; ignore unrelated problems | TCR-007, 010 | TCR-028 |
| A03 | Necessary related-file inspection | TCR-007 | TCR-028 |
| A04 | Live ticket and approved guideline retrieval | TCR-003, 011–012 | TCR-028 |
| A05 | Explicit missing-context and budget limits | TCR-007–008, 011, 019, 026 | TCR-030 |
| A06 | Reject unapproved rule/permission changes | TCR-006, 009, 012, 014 | TCR-030 |
| A07 | Respect valid exceptions, reject expired ones | TCR-013 | TCR-029 |
| A08 | Expose policy conflict or changed wiki text | TCR-012 | TCR-030 |
| A09 | Learning changes behavior only after approval | TCR-022–023 | TCR-029 |
| A10 | Reject unauthorized/stale approvals | TCR-023 | TCR-029 |
| A11 | Clear explanations and supported reassessment | TCR-020–021 | TCR-029 |
| A12 | No duplicates or outdated results | TCR-015, 017–018, 026 | TCR-031 |
| A13 | Same skills through two real model providers | TCR-002, 009, 024–025 | TCR-032 |
| A14 | No unsolicited application-test assessment | TCR-007, 010 | TCR-028, 030 |
| A15 | Incomplete required review cannot pass | TCR-019 | TCR-030–031 |
| A16 | Private-source disclosure is controlled | TCR-014, 020 | TCR-030 |

**MVP sign-off:** the implementation tickets are accepted, the end-to-end tickets pass, and TCR-032 links the final evidence. Setup/access decisions still open in the technical spec are resolved through TCR-001–003; this document does not assume those accounts or connections already work.

**Setup sign-off:** TCR-001A–001E provide evidence that the requested layout, OOP/provider boundaries, meaningful testing, backend CI/coverage/quality merge gate, and safe development practices are implemented. There are 32 parent tickets plus five setup subtasks; the original 16 product acceptance scenarios remain unchanged.

**Verification basis:** all 12 PRD requirement areas and all 16 technical-spec acceptance scenarios were checked when preparing this backlog. Ticket wording, grouping, and dependencies are planning decisions derived from the spec; acceptance criteria describe intended behavior, not completed work. The coverage table is the starting point for the development record.
