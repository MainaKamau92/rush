# rush

Open-source, model-independent code review grounded in approved team standards
and task context.

The intended flow is PR → bounded investigation → evidence-backed findings →
human clarification → evaluated and approved learning. Initial setup adds the
service shell and durable state; review/model/MCP features remain future tickets.

## Run with Docker

Requirements: Docker Engine/Desktop and Docker Compose. No host Python, uv, or
virtual environment is required. No external credentials are needed for setup.

```sh
docker compose build app dev
docker compose run --rm app rush migrate
docker compose up -d --wait app
curl --fail http://localhost:8088/health
docker compose run --rm app rush health
```

The app uses one Uvicorn worker and the persistent `rush-state` named volume.
Migrations run only through `rush migrate`, never as a server-startup side effect.
Without initialization the server fails startup. Stop with `docker compose down`;
do not remove the state volume. Rebuild images after code or dependency changes.
Only the development tool container mounts the checkout; production runs its
installed wheel as a non-root user with a read-only root filesystem.

## Tests and checks

```sh
docker compose run --rm dev pytest
docker compose run --rm dev ruff format --check .
docker compose run --rm dev ruff check .
docker compose run --rm dev mypy
docker compose run --rm dev python scripts/check_architecture.py
docker compose run --rm dev lint-imports
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the remaining required checks, ticket
branches, and PR policy. [Operations](docs/operations.md) covers configuration,
backups, restoration, upgrades, and dependency changes.

## Endpoints and commands

`GET /health` returns readiness and schema version without sensitive settings.
`rush migrate`, `rush health`, and `rush backup /state/backup.sqlite3` use the same
configuration/service wiring. Product review commands are not implemented yet.

## Project documents

- [Shared project knowledge and session starting point](knowledge/index.md)
- [Current work, blockers, and next action](knowledge/current-state.md)
- [Product requirements](docs/product-requirements.md)
- [Current technical specification](docs/technical-spec.md)
- [Development guide](docs/development-guide.md)
- [MVP tickets](docs/mvp-backlog.md)
- [Setup decisions and evidence](docs/setup-record.md)

The public repository is [MainaKamau92/rush](https://github.com/MainaKamau92/rush).
The application and CLI are named rush; the Python distribution is `rush-reviewer`.
Licensed under [MIT](LICENSE).

Agents read the wiki through the repository instructions and update it as they
work. To print the starting context without chat history, run
`docker compose run --rm -T dev python scripts/knowledge.py context`.
