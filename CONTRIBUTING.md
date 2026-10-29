# Contributing to rush

Read the [development guide](docs/development-guide.md), [agent instructions](AGENTS.md),
and the relevant [ticket](docs/mvp-backlog.md) before changing code.

## One ticket, one review

Start from current `main` with a short-lived ticket branch:

```sh
git switch main
git pull --ff-only
git switch -c task/TCR-001-project-setup
```

Use `story/TCR-NNN-description`, `task/TCR-NNN-description`, or
`bug/TCR-NNN-description`. Preserve TCR IDs even when linked to another tracker.
Setup subtasks TCR-001A–001E are delivered together under parent TCR-001.

Commits use `TCR-001-task(setup): establish Docker startup` with a short imperative
subject, an explanatory body when useful, and `Refs: TCR-001` in the footer.
Allowed commit types: `story`, `fix`, `docs`, `style`, `refactor`, `test`, `task`.
Keep commit message lines within 100 characters and omit AI/co-author attribution.

PR title: `[TCR-001] Establish rush project setup`. Use the PR template's Description,
Type of change, How this was tested, Checklist, and Ticket sections. Explain the
behavior, reason, tests, limitations, and any configuration/migration effects.
Finish the ticket, open its PR, and wait for human review and merging before
starting another ticket. Do not merge your own PR or enable automatic merging.

## Docker development checks

Build with `docker compose build dev`. No host virtual environment is needed.
The dev service mounts this checkout and uses disposable test state under `/tmp`.

```sh
docker compose run --rm dev ruff format --check .
docker compose run --rm dev ruff check .
docker compose run --rm dev mypy
docker compose run --rm dev python scripts/check_architecture.py
docker compose run --rm dev lint-imports
docker compose run --rm dev pylint app
docker compose run --rm dev pytest
docker compose run --rm dev bandit -c pyproject.toml -r app scripts
docker compose run --rm dev pip-audit --strict --disable-pip --no-deps -r requirements/development.txt --progress-spinner off
```

GitHub Actions enforces overall and changed-line coverage against the actual PR
base. No changed executable lines means not applicable, not an invented 100%.
Missing reports/history fail. Local coverage reports are optional:
`docker compose run --rm dev pytest --cov --cov-report=term-missing`.
CI also validates the workflow with actionlint and scans Git history with
checksum-pinned Gitleaks. Its final merge gate checks prerequisite job results
directly, without a local gate script.

Most tests should protect service behavior and regressions. Use real temporary
SQLite for storage/migrations, controlled external substitutes, and no live keys.
Overall statement/branch coverage starts at 80%; changed executable lines at 90%.
Critical failures need explicit tests regardless of percentages. Explain and
obtain review for changes to workflows, thresholds, exclusions, or allowlists.

Quick hooks use Docker and the committed `.pre-commit-config.yaml`. To install
without a host pre-commit environment, use `scripts/install-hooks.sh`; configure
the commit template with `git config commit.template .github/commit-message-template.txt`.
The installed outer hook starts the dev container; the hook entries invoke tools
inside it, so neither a Docker socket nor a nested Docker client is mounted.
Hooks are convenience checks; required CI still judges the current revision.

## Review, shared history, and releases

The initial maintainer is MainaKamau92. This is a solo setup: the owner reviews
the PR explicitly, including changes to quality controls. It does not claim
independent approval. Once an eligible teammate joins, require independent
approval and update repository protection and the setup record together.
Failing, skipped, missing, or cancelled machine prerequisites never permit merge;
elapsed time and absent reviewers do not waive them.

Use small PRs into `main`; no `develop` or release branch is required. Resolve
conflicts deliberately and rerun affected checks. Rebase only your own unshared
branch; never rewrite shared `main`. If an authorized personal-branch rewrite
must be pushed, use an explicit expected-value lease. Revert shared mistakes
with a reviewed PR. Urgent fixes use ticket-linked `bug/` branches and the same
checks. Tag accepted releases as `vMAJOR.MINOR.PATCH`, documenting the exact
revision, migration, verification evidence, and remaining limitations.
