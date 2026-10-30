# rush

Open-source, model-independent code review grounded in approved team standards
and task context.

The intended flow is PR → bounded investigation → evidence-backed findings →
human clarification → evaluated and approved learning. Initial setup adds the
service shell and durable state; TCR-002 adds a bounded Meta model access check.
TCR-003 adds approved ClickUp reads through MCP. The review workflow remains
future work.

The hackathon uses Meta models; other providers are deferred behind the shared
provider interface. Comparing Meta models does not prove cross-provider support.

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

`rush model-check --model MODEL_ID` verifies one explicitly selected model with
a fixed public prompt. It prints model identity and usage, without raw output
or credentials. To opt into a live check using `META_AI_KEY` from local `.env`:

```sh
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev rush model-check --model muse-spark-1.3
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev rush model-check --model muse-wonder-1.0
```

These calls can incur charges. The separate override forwards only the selected
credential/configuration to the dev container; ordinary tests and CI do not use
it. See [model access and evidence](knowledge/model-access.md) for setup,
limits, privacy settings, and the unconfirmed account details.

`rush source-connect`, `source-status`, `source-tools` and `source-read` check
read access to the approved ClickUp ticket and guideline through MCP. They print
tool names, hashes and lengths, never page text or credentials. Live use needs
the `compose.source-access.yaml` override and local settings; see
[source access](knowledge/source-access.md) for setup and reconnect steps.

## Project documents

[Fictional customer lookup examples](tests/fixtures/customer_lookup/README.md)
provide safe/unsafe changes, frozen context and expected outcomes. Reset and
verify them through Docker without credentials or model calls.

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
