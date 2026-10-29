---
type: Working Agreement
title: Working agreements
description: Branches, commits, PRs, comments, and review replies.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T17:52:29Z"}
sources:
  - id: agents
    resource: https://github.com/MainaKamau92/rush/blob/main/AGENTS.md
    x_repo_path: AGENTS.md
    x_sha256: a11be1ec8271463069816be8a0d4f531ee9b6b2928683790a147e1bcb3a1eb7c
  - id: guide
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/development-guide.md
    x_repo_path: docs/development-guide.md
    x_sha256: 8d6f5a0e88f9308e0d1f947a83f335733f4721bc03a1e183198b00f7b514f0e8
---
# Working agreements

Read the relevant backlog ticket and development guide. Start short-lived
`story/TCR-NNN-description`, `task/TCR-NNN-description`, or
`bug/TCR-NNN-description` branches from current main. Commits use
`TCR-NNN-task(scope): imperative subject` with the appropriate allowed type
and `Refs: TCR-NNN` footer. Do not add AI/co-author attribution to commits.[^guide]

PRs use `[TCR-NNN] Imperative subject` and the required sections: Description,
Type of change, How this was tested, Checklist, and Ticket. Describe behavior,
why, verification, and limitations. Pass required checks, wait for human review
and merging, and never merge our own PR or start the next ticket early.[^agents]

Use the existing TCR backlog references in branches, commits, and PRs. Do not
create a paired GitHub issue unless the owner asks for it. Previously created
issues are historical records, not a requirement to continue that workflow.

Reply to the original review comment before resolving its thread. Briefly say
what changed or explain evidence-backed pushback; keep disputed issues open.
Review replies end on a separate line with `-- Codex ({{modelversion}})` using
the verified active model version. Its absence is a real information gap, not
permission to guess. Keep replies short and plain.[^agents]

Maintain [current work](current-state.md) and affected pages during the task,
before opening/updating a PR, and before stopping. Follow
[maintenance](maintenance.md). Knowledge updates belong in the same focused PR;
do not copy private chat logs or credentials into this public repository.

[^agents]: Repository working instructions.
[^guide]: Commit, branch, PR, and review conventions.
