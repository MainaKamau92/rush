# Docker operation and recovery

## Configuration and state

Docker Compose supplies `RUSH_STATE_DIR=/state` and
`RUSH_ENVIRONMENT=production`. The state directory must be absolute; environment
must be `development`, `test`, or `production`. Missing/invalid settings fail
without printing supplied values. Team policy will be configured separately
from deployment credentials when those features are implemented.

No host venv is needed. The image installs locked, hash-checked dependencies into
its system Python. Production uses a built/installed wheel and one worker;
development checks use the separate `dev` target. Both share Python 3.12.13.
SQLite's exact runtime version is recorded in setup evidence from the image.

The `rush-state` named volume persists across container restarts and ordinary
`docker compose down`. Do not delete it or run multiple app replicas against it.
No reviewed code, provider calls, review worker, approvals, or publication are
implemented by TCR-001. Future tickets must persist their state in this database.

## Build, release, run

1. Build the exact reviewed revision with `docker compose build app dev`.
2. Stop the app before upgrading: `docker compose stop app`.
3. Back up existing state before applying a new migration.
4. Run the selected image's explicit `rush migrate` command once.
5. Start with `docker compose up -d --wait app` and verify `/health`.

Startup does not apply migrations. Concurrent migration commands serialize using
SQLite's immediate transaction; failures roll back. Applied SQL file digests
are checked by the migration command; never edit an applied file. Add a new
numbered revision and integration-test fresh setup and upgrade/data preservation.

Logs go to stdout/stderr (`docker compose logs app`). Setup endpoints do not log
settings or request bodies. Future run/request identifiers belong in the relevant
feature tickets; setup does not invent review runs to demonstrate logging.

## Backup, export, and restore

Create a consistent backup with a fresh destination filename:

```sh
docker compose run --rm app rush backup /state/backup-before-upgrade.sqlite3
docker compose cp app:/state/backup-before-upgrade.sqlite3 ./backup-before-upgrade.sqlite3
```

If the app container does not exist, create it with `docker compose create app`
before the copy. Keep exports outside Git in protected storage. The backup
command refuses to overwrite an existing backup. A database backup is also the
setup-state export; portable approved-rule exports arrive in TCR-023.

For recovery, stop the app, retain the failed database separately, and copy a
verified backup to `/state/rush.sqlite3` using a maintenance container attached
to the same volume. For example, with the backup in the checkout:

```sh
docker compose stop app
docker compose run --rm --user root --entrypoint sh -v "$PWD:/recovery:ro" app -c 'cp /state/rush.sqlite3 /state/rush-before-restore.sqlite3 && cp /recovery/backup-before-upgrade.sqlite3 /state/rush.sqlite3 && chown rush:rush /state/rush.sqlite3'
docker compose run --rm app rush health
docker compose up -d --wait app
```

Use an image compatible with the restored schema. Do not automatically downgrade
schemas. Prefer a tested forward repair; preserve a backup before any destructive
change. Before deleting data, identify the exact database/export and authorize
that deletion explicitly; never delete a volume merely to fix startup.

## Dependencies and secrets

Edit `pyproject.toml` intentionally, regenerate `uv.lock` and its three
hash-checked requirements exports with the pinned uv tool in a container, then
rebuild/test both images:

```sh
sh scripts/lock-dependencies.sh
docker compose build app dev
```

Never commit real `.env` files, credentials, private data, source captures,
database files, or backups. `.env.example` contains placeholders only. Containers
do not receive live model/MCP credentials during CI. If a credential leaks,
revoke/rotate it first, assess exposure and dependent access, then coordinate
history/log cleanup; rewriting Git history does not contain the credential.

## Meta model access checks

TCR-002 adds the explicit `rush model-check --model MODEL_ID` command. It does
not run on startup or require a database migration. Use the separate
`compose.model-access.yaml` override only for trusted live checks, as documented
in [model access](../knowledge/model-access.md). Do not print its resolved
Compose configuration or enable request/header debug logging with real keys.

| Setting | Meaning |
|---|---|
| `META_AI_KEY` | Owner's credential variable; read from the local `.env` by Compose and forwarded only by the live-check override. |
| `RUSH_META_BASE_URL` | Trusted HTTPS API base; defaults to `https://api.meta.ai/v1`. No redirects or endpoint fallback. |
| `RUSH_MODEL_TIMEOUT_SECONDS` | Per-request and total access-check deadline, default 30 seconds, maximum 60. |

Each command sends only `Reply with RUSH_OK.`, caps generated/reasoning output at
128 tokens, requests `store: false`, and uses minimal reasoning. No retries or
model/provider fallback occur. Contributor model IDs are rejected before a
request; enabling another data mode requires a separate reviewed change.
`store: false` is a response-storage setting, not a claim of zero provider
retention. Replace the key through the Meta dashboard and update local secret
injection when rotating credentials; never commit it.
