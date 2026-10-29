---
type: Playbook
title: Maintenance
description: Startup, source ingestion, updates, and freshness rules.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: wiki
    resource: references/llm-wiki.md
  - id: okf
    resource: references/open-knowledge-format.md
  - id: owner
    resource: references/owner-instructions-2026-10-29.md
---
# Maintenance

## Start a session

1. Read local AGENTS.md, [the index](index.md), and [current work](current-state.md).
2. Run `git status --short --branch` and `git log -1 --oneline`. Verify relevant
   PR state and checks on GitHub before treating a task as merged or approved.
   If offline, label remote state unverified and avoid actions that depend on it.
3. Follow topic links and their sources as needed. Current owner instructions
   and canonical project documents govern; summaries cannot override them.
4. Use `docker compose run --rm -T dev python scripts/knowledge.py context` to
   validate and print the starting pages. The command reads files, not chat
   history, secrets, or remote accounts. It does not fetch live GitHub state.

## Update knowledge while working

Capture durable choices, behavior, evidence, unexpected failures, and unresolved
questions in the relevant topic. Keep current-state short: active ticket/branch,
completed work, paused work, checks actually run, blockers, and the next action.
Update before stopping, handing off, or opening/updating a PR; do not wait for
the owner to ask. Changes must match the actual work, including partial results.

Do not stamp a PR as merged in advance. After a later session verifies a merge,
record the observation with its URL and revision. A log entry is a dated event;
the current-state page is the resumable checkpoint.

## Add a source

Read the source, add its URL or an immutable source record, extract only what
matters, and update related topics and directory indexes. Cite individual claims
with footnotes keyed to `sources[].id`. Leave original project documents and
external sources intact; summaries live here.[^wiki]

Owner directions without public links can be captured in a minimal, dated
reference record, explicitly identified as a conversation summary. Never store
whole private transcripts, API keys, account screenshots, prompts with private
code, or raw provider responses. Credential variable names are sufficient.

Preserve dated instruction records. If new instructions supersede an earlier
decision, add a new source record, update the synthesis, and note the conflict
and resolution. Do not quietly rewrite history or infer human approval.

## Format and freshness

This bundle targets OKF 0.2.[^okf] Concepts carry `type`, `title`, `description`,
`generated`, and `sources`. The last four are our project requirements, stricter
than OKF's minimum. Unknown types and extra fields are allowed. Use `status:
draft` until the content is reviewed; no `verified` entry may claim a human
review that did not happen. `codex/unreported` explicitly means the active
model version was unavailable, not a verified model identifier.

Use timezone-qualified ISO timestamps for meaningful edits. Local-source
extensions `x_repo_path` and `x_sha256` bind a summary to the exact source file.
When its digest changes, reread the source, refresh affected claims, then update
the digest using `sha256sum <path>` in the dev container. Never just refresh a
hash to silence a failure. Remote sources need live rechecking when a decision
depends on current pricing, availability, access, or PR/check status.

Each directory has an index linking its direct pages and child indexes. Only
the root index has frontmatter (`okf_version`); logs have none. Add dated events
under newest-first `YYYY-MM-DD` headings in [the log](log.md), preserving older
entries. This follows OKF's log layout; it is not a chat transcript.

## Check and hand off

Run `docker compose run --rm -T dev python scripts/knowledge.py check`. It checks
our metadata, indexes, file links, source fingerprints, and log layout. Project
links must resolve even though OKF consumers are allowed to tolerate missing
targets. It does not prove prose is correct, validate every optional OKF field,
check remote URLs, or replace human review. Use ordinary inline Markdown links;
the checker skips fenced examples and does not resolve heading anchors.

Scan for stale claims, conflicting decisions, and missing evidence. Run the
CONTRIBUTING.md checks, commit safe knowledge with the task, push its branch,
and link the PR. Unpushed work exists only in that checkout; other machines
need the published branch or an explicit file export. No cloud service, model
call, embedding database, or account is required for this wiki.

AGENTS.md enables startup and maintenance for agents that follow repository
instructions; CLAUDE.md points to it. An agent that ignores these files needs
its own instruction configuration. This setup cannot force an arbitrary client
to load context, or recover changes never saved to disk.

[^wiki]: Karpathy's source/wiki/instruction pattern, adapted for this repository.
[^okf]: Canonical format revision and migration note.
[^owner]: Owner request for shared session/agent knowledge.
