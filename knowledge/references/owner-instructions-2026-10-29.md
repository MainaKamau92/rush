---
type: Source Record
title: Owner instructions recorded 2026-10-29
description: Safe capture of project choices and current priority.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: conversation
    resource: Owner instructions supplied in the rush setup conversation and 2026-10-29 session
---
# Owner instructions recorded 2026-10-29

This is a curated record of instructions supplied in the conversation, not a
full transcript or an independently reviewed source. It contains no credential
values. Preserve it; capture later changes in a new dated record.

- The application is rush, not Team Code Reviewer; keep existing TCR ticket IDs.
- The owner selected the MIT license and a public repository.
- Run/test with Docker; a host venv is unnecessary.
- Finish one ticket, open its PR, and wait for human review and merging before
  starting the next. Do not merge our own PR.
- Avoid unnecessary inline comments/docstrings; never add filler to empty
  modules, classes, methods, or functions.
- Reply to the initial review comment before resolving its thread, explaining
  the fix or justified pushback. Sign review replies `-- Codex ({{modelversion}})`.
  Keep responses succinct and avoid unnecessary technical jargon.
- The owner confirmed PR #2 was merged and asked to begin the next task.
- For TCR-002, the owner wants Meta models and said the key is stored locally
  in `.env` under `META_AI_KEY`. No issuing host, exact model, second provider,
  billing permission, or account data policy was confirmed in that reply.
- The owner then asked to set up the supplied Karpathy gist and Google OKF
  approach first, so sessions/agents can share knowledge without pasted handovers,
  and return to TCR-002 afterwards.

The workflow and implementation instructions are also maintained in AGENTS.md.
Read [decisions](../decisions.md) and [current work](../current-state.md) for
the current synthesis. These notes record instructions, not a new approval.
