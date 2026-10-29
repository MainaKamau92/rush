---
type: Architecture
title: Architecture
description: Where behavior belongs and how to run and check the app.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T10:04:28Z"}
sources:
  - id: guide
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/development-guide.md
    x_repo_path: docs/development-guide.md
    x_sha256: 2976b685d1a00d73ee4d50e1b6c0511c42350a9b113d8d7c8c02f89172bd28f8
  - id: contributing
    resource: https://github.com/MainaKamau92/rush/blob/main/CONTRIBUTING.md
    x_repo_path: CONTRIBUTING.md
    x_sha256: 51b85ab92c4b4fdaa106ba485d8bc53ed06a7348ccbc2511af43b4606a63a92a
  - id: operations
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/operations.md
    x_repo_path: docs/operations.md
    x_sha256: 98b7842374bea8371c7c1b2275f90c5967b9eeef0844ea79c3553e34d9c6efa1
---
# Architecture

Python/FastAPI uses package `app` and CLI `rush`. Focused service classes own
business workflows and accept interfaces through their constructors. Define
interfaces in `app/services/ports.py`, external clients in
`app/internal/adapters/`, repositories in `app/db/repositories/`, and assemble
them in `app/dependencies.py`. Routers and CLI handle input/output and delegate;
they do not query the database or make review decisions.[^guide]

The existing example is health router → `SystemService` → `StateRepository`,
with `SQLiteStateRepository` selected in the assembly module. Preserve the
required layout without adding unused abstractions, an ORM, frontend, or queue.

The access-check path is CLI → `ModelAccessService` → `TextModelProvider`, with
`MetaModelProvider` and its HTTPX client assembled only in `app/dependencies.py`.
The service uses a fixed public prompt and an explicit model ID. Other providers
remain deferred; this boundary is not a claim of live cross-provider support.

## Operation

Use Docker Compose; no host venv is required. Build `app dev`, explicitly run
`docker compose run --rm app rush migrate`, then start the app with
`docker compose up -d --wait app`. SQLite lives on persistent state; keep one
instance/worker, never edit an applied migration, and never delete its volume
as a recovery shortcut. Follow `docs/operations.md` for backup/restore.[^operations]

## Verification

Run the commands in CONTRIBUTING.md through the dev container: format, lint,
types, architecture/import boundaries, duplication, tests, Bandit, dependency
audit, and the knowledge check. Ordinary tests have no live credentials; use
real temporary SQLite for persistence behavior.[^contributing]

CI enforces combined statement/branch coverage and changed-line coverage and
requires `backend-required`. Do not lower thresholds or bypass a failed check.
See [working agreements](workflow.md) and [current work](current-state.md).

[^guide]: Required layout and service responsibilities.
[^contributing]: Required checks and coverage policy.
[^operations]: Explicit migrations, persistent state, and recovery.
