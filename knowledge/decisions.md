---
type: Decision Record
title: Decisions
description: Owner choices that future sessions must preserve.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T17:52:29Z"}
sources:
  - id: owner
    resource: references/owner-instructions-2026-10-29.md
  - id: model-scope
    resource: references/owner-model-scope-2026-10-29.md
  - id: provider-pattern
    resource: references/provider-pattern-2026-10-29.md
  - id: source-scope
    resource: references/owner-source-scope-2026-10-29.md
  - id: agents
    resource: https://github.com/MainaKamau92/rush/blob/main/AGENTS.md
    x_repo_path: AGENTS.md
    x_sha256: a11be1ec8271463069816be8a0d4f531ee9b6b2928683790a147e1bcb3a1eb7c
  - id: setup
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/setup-record.md
    x_repo_path: docs/setup-record.md
    x_sha256: 26dad4ec806348df0ca9d90c38304141b35d9521f2aaaab756d973ba7a89b4d6
---
# Decisions

| Decision | Reason / source |
|---|---|
| Name the app, CLI, images, and docs rush; keep TCR IDs. | Explicit owner direction; package is `app`, distribution `rush-reviewer`.[^agents] |
| Public repository and MIT license. | Owner-selected setup decisions.[^setup] |
| Docker is the supported run/test workflow; no host venv. | Explicit owner direction.[^owner] |
| One ticket, then its PR, human review, and merge before the next. | Explicit owner direction; never merge our own PR.[^agents] |
| Prefer self-explanatory code; avoid unnecessary comments/docstrings and empty placeholders. | Explicit owner direction.[^agents] |
| Reply to the initial review comment before resolving; justify disagreement and leave it open. | Explicit owner direction.[^owner] |
| Review replies end with `-- Codex ({{modelversion}})`, using a verified model version. | Owner-requested format; do not invent a version or claim a configured default is the active model.[^agents] |
| Keep responses short, plain, and supported by evidence. | Explicit owner direction.[^agents] |
| Set up shared knowledge before resuming TCR-002. | Explicit priority change, not completion of model access.[^owner] |
| Use Meta models for the hackathon, keeping provider interfaces replaceable. | Latest owner scope; other providers and live cross-provider proof are deferred.[^model-scope] |
| Small paid model access checks are allowed. | Owner authorized bounded tests; this does not authorize unbounded usage or Contributor mode.[^model-scope] |
| Follow the sample's provider contract / selection / vendor adapter layout. | Owner clarified the PR #8 review; keep instance construction in dependencies.py.[^provider-pattern] |
| Use existing TCR references without extra paired GitHub issues unless asked. | Workflow clarification following the owner's question about issue creation.[^provider-pattern] |
| ClickUp only for TCR-003: a task as the ticket, a Doc page as the guideline. | Owner choice; Notion is not part of the demo source pair.[^source-scope] |
| Keep approved workspace and resource IDs local; record only hashes and lengths. | Owner disclosure rule for this public repository.[^source-scope] |

These summaries do not grant new permissions. Apply the current instructions,
check the sources when a decision changes, and record contradictions explicitly.
See [working agreements](workflow.md), [maintenance](maintenance.md),
[model access](model-access.md), and [source access](source-access.md).

[^owner]: Captured owner instructions.
[^agents]: Repository working instructions.
[^setup]: Setup decisions and evidence.
[^model-scope]: Latest owner model scope and test permission.
[^provider-pattern]: Provider review clarification and issue-tracking agreement.
[^source-scope]: TCR-003 source pair and resource-ID disclosure rule.
