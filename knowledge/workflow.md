---
type: Working Agreement
title: Working agreements
description: Branches, commits, PRs, comments, and review replies.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T10:04:28Z"}
sources:
  - id: agents
    resource: https://github.com/MainaKamau92/rush/blob/main/AGENTS.md
    x_repo_path: AGENTS.md
    x_sha256: 2ed408cfc6383aa6f365d7e04ca3291a369cbf801c32adaf318a651a4e3f3592
  - id: guide
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/development-guide.md
    x_repo_path: docs/development-guide.md
    x_sha256: 2976b685d1a00d73ee4d50e1b6c0511c42350a9b113d8d7c8c02f89172bd28f8
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
