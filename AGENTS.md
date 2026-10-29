# rush working instructions

The application, CLI, images, and documentation are named **rush**. Preserve
existing TCR ticket IDs. The Python package is `app`; the distribution is
`rush-reviewer` to distinguish it from unrelated Python packages.

## Ticket and review workflow

- Read `docs/development-guide.md` and the ticket in `docs/mvp-backlog.md`.
- Use short-lived `story/TCR-NNN-description`, `task/TCR-NNN-description`, or
  `bug/TCR-NNN-description` branches from current `main`.
- Commits: `TCR-NNN-task(scope): imperative subject`; use the guide's allowed types
  and add `Refs: TCR-NNN` in the footer. No AI/co-author attribution.
- PRs: `[TCR-NNN] Imperative subject`, using the required description sections.
- Finish one ticket, open its PR, and wait for human review and merging before
  starting the next ticket. Do not merge your own PR or bypass failing checks.
- TCR-001A–001E are the setup subtasks of parent TCR-001, delivered in its setup PR.

## Implementation

- Docker Compose is the supported run/test workflow; no host venv is required.
- Keep the required `app/` structure. Business workflows belong in focused service
  classes with constructor-injected interfaces in `app/services/ports.py`.
- External clients live in `app/internal/adapters/`, persistence implementations
  in `app/db/repositories/`; assemble them only in `app/dependencies.py`.
- Routers and CLI handle input/output and delegate; no business rules or DB calls.
- Do not add unused base classes, artificial wrappers, frontend, ORM, or queues.
- Prefer self-explanatory code. Do not add inline comments or docstrings when
  the code can explain the behavior; explain only necessary, non-obvious reasons
  or constraints that the code cannot express clearly.
- Do not add comments or docstrings to empty modules, classes, methods, or
  functions, or use them as placeholder content.
- Use the current `docs/technical-spec.md`; the archive is historical.
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

Be honest and avoid sycophancy. Challenge weak ideas with evidence when needed.
For replies longer than a few sentences that contain factual claims, check those
claims against actual files, links, or observed data. Label unverified claims
`[UNVERIFIED]`, list them, end with a short verified-claims count and sources,
and offer a verification table. Never present a guess as fact.
