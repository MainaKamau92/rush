# rush working instructions

The application, CLI, images, and documentation are named **rush**. Preserve
existing TCR ticket IDs. The Python package is `app`; the distribution is
`rush-reviewer` to distinguish it from unrelated Python packages.

## Session continuity

- `knowledge/` is internal, local-only agent context. Keep its files on disk,
  excluded from Git and Docker images. Never add, force-add, copy into public
  documentation, or reintroduce the folder to version control.
- When local knowledge is present, start every session by reading `knowledge/index.md`,
  `knowledge/current-state.md`, and `knowledge/maintenance.md` before working.
  Follow the index to the relevant topic and its sources rather than rereading
  every project document or relying on chat history.
- A fresh clone may have no `knowledge/`. In that case read the development guide,
  technical specification and backlog; do not invent previous work or decisions.
- Check the actual branch, working tree, commits, and relevant GitHub PR/checks
  before acting. Recorded state is a dated observation, not live authorization.
- Maintain the wiki automatically as work progresses. Before stopping, handing
  off, or opening/updating a PR, refresh current work, decisions, evidence,
  blockers, and the next action; update affected topic pages and the index;
  add an entry to `knowledge/log.md`. Do not wait for a handover request.
- Follow the source, privacy, freshness, and conflict rules in
  `knowledge/maintenance.md`. Never store secrets or whole private transcripts.
- Run `docker compose run --rm -T dev python scripts/knowledge.py check` after
  knowledge changes. `context` prints the starting pages for another session.
- Another agent needs access to the local knowledge files and these instructions;
  a Git clone does not transfer the internal folder. Files do
  not configure an agent that ignores repository instructions or lacks access.

## Ticket and review workflow

- Read `docs/development-guide.md` and the ticket in `docs/mvp-backlog.md`.
- Use short-lived `story/TCR-NNN-description`, `task/TCR-NNN-description`, or
  `bug/TCR-NNN-description` branches from current `main`.
- Commits: `TCR-NNN-task(scope): imperative subject`; use the guide's allowed types
  and add `Refs: TCR-NNN` in the footer. No AI/co-author attribution.
- PRs: `[TCR-NNN] Imperative subject`, using the required description sections.
- Use the existing TCR backlog references; do not create paired GitHub issues
  unless the owner asks for them.
- Reply to the initial review comment before resolving its thread. Briefly explain
  what was addressed, or give a reasoned pushback with evidence when necessary.
  Leave disputed points open for the reviewer.
- Keep review replies short and use plain language. End each reply on a separate
  line with `-- Codex ({{modelversion}})`, using the verified active model version.
  Do not invent a model version if it is unavailable.
- Finish one ticket, open its PR, and wait for human review and merging before
  starting the next ticket. Do not merge your own PR or bypass failing checks.
- TCR-001A–001E are the setup subtasks of parent TCR-001, delivered in its setup PR.

## Implementation

- Docker Compose is the supported run/test workflow; no host venv is required.
- Keep the required `app/` structure. Business workflows belong in focused service
  classes with constructor-injected interfaces. Third-party provider contracts
  live in `app/provider/<capability>/abstract.py`; `base.py` selects the adapter
  class. Repository ports remain in `app/services/ports.py`.
- External clients live in `app/internal/adapters/`, persistence implementations
  in `app/db/repositories/`; assemble objects only in `app/dependencies.py`.
- Follow the owner-supplied sample pattern: services import the abstract provider,
  adapters implement it, and the selection module exports the chosen adapter
  class without creating a client or instance at import time.
- Routers and CLI handle input/output and delegate; no business rules or DB calls.
- Do not add unused base classes, artificial wrappers, frontend, ORM, or queues.
- Prefer self-explanatory code. Do not add inline comments or docstrings when
  the code can explain the behavior; explain only necessary, non-obvious reasons
  or constraints that the code cannot express clearly.
- Do not add comments or docstrings to empty modules, classes, methods, or
  functions, or use them as placeholder content.
- Use the current `docs/technical-spec.md`; the archive is historical.
- Use Meta models for the hackathon; other providers are deferred. Preserve
  injected provider interfaces without claiming untested cross-provider support.
- No next-ticket product features as part of setup.

## Verification and operation

- Test behavior and regressions, with real temporary SQLite for persistence.
  Do not test framework internals or manufacture tests for coverage.
- Enforce 80% combined statement/branch coverage and 90% changed executable lines
  in GitHub Actions; missing data fails. Local coverage reports are optional.
  Threshold/exclusion changes need explicit review.
- Run the checks documented in CONTRIBUTING.md through Docker before committing.
- PR CI has no live provider or production credentials. Never expose real secrets
  in prompts, logs, fixtures, public documents, or example settings.
- Apply migrations explicitly; never edit an applied migration. Keep SQLite
  persistent and run a single app instance/worker. Never delete a state volume
  as a troubleshooting shortcut.

## Communication

Keep responses succinct and use plain language; avoid unnecessary technical jargon.

Be honest and avoid sycophancy. Challenge weak ideas with evidence when needed.
For replies longer than a few sentences that contain factual claims, check those
claims against actual files, links, or observed data. Label unverified claims
`[UNVERIFIED]`, list them, end with a short verified-claims count and sources,
and offer a verification table. Never present a guess as fact.
