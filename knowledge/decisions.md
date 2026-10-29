---
type: Decision Record
title: Decisions
description: Owner choices that future sessions must preserve.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: owner
    resource: references/owner-instructions-2026-10-29.md
  - id: agents
    resource: https://github.com/MainaKamau92/rush/blob/main/AGENTS.md
    x_repo_path: AGENTS.md
    x_sha256: 1801b112f52734b53e1800529d5cbfda13506752827efe892a5cb524b8e29c88
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

These summaries do not grant new permissions. Apply the current instructions,
check the sources when a decision changes, and record contradictions explicitly.
See [working agreements](workflow.md), [maintenance](maintenance.md), and
[model access](model-access.md).

[^owner]: Captured owner instructions.
[^agents]: Repository working instructions.
[^setup]: Setup decisions and evidence.
