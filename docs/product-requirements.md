# rush — Minimal PRD

## Goal

Build an open-source, model-independent reviewer that reviews code changes against team standards and relevant task context, explains actionable findings clearly, and learns through approved team feedback.

**Users:** developers submitting changes and teammates reviewing them.

**Core flow:** PR → scoped diff and necessary context → review skills → evidence-backed findings → human clarification or correction → re-review.

## Requirements

| Area | Required behavior |
|---|---|
| Review scope | Find correctness, regression, compatibility, architectural-consistency, and completeness issues attributable to the diff. Report apparent security problems encountered during review. Avoid unrelated cleanup suggestions. |
| Bounded investigation | Start with the diff. Read outside it only to answer a necessary question through a direct caller, dependency, interface, or configuration relationship. Record the reason, enforce investigation limits, and stop when the question is resolved. Disclose unresolved context gaps. |
| Tests | No coverage assessment or general test-quality checks by default. Inspect or run tests only to understand or verify a specific issue in the diff, or when explicitly required by the team. Leave broader test judgment to humans. |
| MCP context | Retrieve linked ClickUp/Jira tickets and relevant team guidelines from configured ClickUp/Notion wikis through MCP. Prefer explicit links and approved guideline locations; use narrowly scoped search only when needed. Cite the source and relevant passage, record its version or retrieval time, and report inaccessible, missing, or conflicting context. |
| Team standards | Load version-controlled rules and approved wiki guidelines; scope them by repository, service, path, or file type. Define precedence and support documented exceptions with owners and optional expiry. Surface unresolved conflicts rather than silently choosing a rule. |
| Review skills | Support installable, versioned skills containing instructions, scope, tool permissions, and configuration. Include acceptable/violating examples and expected findings to evaluate the skills themselves. |
| Approved memory | Propose learnings from review discussions with source, rationale, owner, and scope. Require authorized approval before enforcement; allow editing, retirement, and expiry. |
| Models and runtime | Run locally or in CI using team-controlled credentials. Select provider/model per skill through replaceable adapters; preserve a common findings format and report unsupported capabilities explicitly. |
| Review workflow | Support automatic/manual triggers, full/incremental review, branch/draft/label/path filters, and pause/resume. Update findings after new commits without duplicating unchanged comments. |
| Findings and dialogue | Publish a concise summary and findings with location, severity, consequence, evidence, and suggested remediation. Explain the causal link to the diff, especially across components/services. Let humans request a concrete example, dependency path, evidence, or simpler explanation; revise or withdraw unsupported findings. |
| Communication | Configure technical complexity and verbosity independently, with team defaults, personal overrides, and per-response requests. Wording preferences must not change review standards, severity, or evidence requirements. |
| Checks and traceability | Default to advisory findings; allow explicitly required checks. Distinguish violations, execution failures, and incomplete reviews. Record commit, model, skill/rule versions, context sources, and finding disposition. Evaluate false positives and missed issues using skill examples and human feedback. |

## Operating boundaries

- Use approved rule/skill revisions; a PR must not silently change the standards or permissions used to review itself. Retrieved tickets supply task context; only designated, approved guideline sources supply enforceable policy.
- Give MCP tools read-only, least-privilege access; control permission to publish PR findings separately. Retrieved content must not grant tools permissions or override reviewer controls.
- Keep dedicated security scanning external, with GitGuardian outside this reviewer’s scope. Exclude general coverage checks, automatic fixes/merges, code generation, status reporting, and post-merge automation.
- Publish source, setup instructions, skill interfaces, and an explicitly selected open-source license.

## Hackathon demonstration

Use a single repository, a small skill bundle, two model adapters, and live MCP context. Demonstrate one ticket source (ClickUp or Jira) and one approved guideline source (ClickUp or Notion); supporting every vendor is not required for the demo.

The demo should show:

1. A PR reviewed against a linked ticket and wiki guideline, with a finding citing both the changed code and applicable context.
2. Necessary dependency inspection with a clear link to the diff; no unrelated investigation or unsolicited test audit.
3. A human requesting clarification and changing verbosity/technical complexity without changing the finding’s substance.
4. An approved learning applied on re-review, plus an explicit exception respected.
5. The same skill evaluated with another model, recording differences rather than promising identical output; unavailable context reported as a limitation, not a pass.

**Basis:** requirements agreed in this conversation. This document specifies intended behavior, not implemented capabilities.
