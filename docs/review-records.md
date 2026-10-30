# Review records and settings

TCR-005 adds the storage and validation layer for later review work. It does not
read a diff, run a model, verify a finding against code, or publish a review.

## Contracts

`app/schemas/review.py` defines shared, versioned Pydantic formats. Unknown fields,
unsupported versions/providers/modes, invalid hashes and nonpositive required
budgets fail validation. JSON numeric fields must contain numbers, not strings.
Settings require one explicit Meta model for the review task, with at most one
model per task. They record model IDs, adapter versions and optional resolved
revisions; an unavailable provider revision stays unknown.

| Format | Records |
|---|---|
| `ReviewSettings` | Advisory/required mode, severity threshold, task models and configured limits. |
| `ReviewInputs` | Repository, optional PR number, target/merge-base/head/policy SHAs, memory revision, rule/skill digests, source snapshots and settings. |
| `SourceSnapshot` | Stable source reference, optional revision, content hash, retrieval time, disclosure label and optional bounded excerpt. |
| `Finding` | Run and skill identity, optional rule version, category/severity, diff anchor, trigger, consequence, evidence, assumptions and disposition. |
| `ReviewResult` | Findings, explicit limitations and recorded usage; unknown token counts remain `null`. |
| `ReviewRecord` | Run identity, frozen inputs and progress events with timestamps and reasons. |

The model stage also records proposed findings separately from canonical
findings, captured code passages, model capabilities/attempts and usage. See
[the model review protocol](model-review.md). Publication/completion is refused
while unvalidated proposals remain. These are additive optional fields; existing
record data loads without a database migration.

The formats are frozen and use tuples for collections, including nested model
settings and sources. The service validates and snapshots inputs on creation;
later configuration changes apply to new runs. A saved run's inputs cannot be
replaced through the repository update operation. These are record formats,
not a skill manifest or an approved-policy registry.

Source and evidence revisions default to `null` when a provider exposes no
version. Retrieval time remains a separate timestamp. Evidence still needs the
frozen source ID and content hash, and any recorded revision must agree.

`model_validate_json()` loads saved JSON; `model_dump_json()` writes it.
`model_json_schema()` exposes the same contract for later integrations.
Formatted validation errors hide input values. Credentials belong in deployment
settings, outside review settings and records.

## Progress and persistence

`ReviewRecordService`, constructed by `build_review_records()` in
`app/dependencies.py`, accepts an injected repository and clock. Its operations
are `create(run_id, inputs)`, `get(run_id)` and
`advance(run_id, status, reason, result=None)`.

The normal sequence is:

```text
queued → preparing → reviewing → validating → publishing → completed
```

Any active stage can instead end as `partial`, `failed`, `superseded`,
`cancelled` or `skipped`. Every event requires a reason and an aware timestamp;
time cannot go backwards. Terminal records cannot reopen. A partial result
requires a limitation. Each limitation has a canonical code and an
`affects_completeness` flag, which defaults to `true`. Only limitations affecting
completeness prevent completion; optional-context notes can remain in a
completed record. The trusted host decides this flag; source text and model
output do not grant permission to downgrade required work.
Omitting `result` retains the previous result; supplying it replaces the current
result explicitly. `status` is the last event's status; `revision` counts
transitions after creation.

Context codes distinguish `missing_ticket`, `access_denied`, `rate_limited`,
`content_truncated`, `guideline_changed` and `conflicting_sources`. Other accepted
codes are `missing_context`, `budget`, `unresolved_question`,
`required_skill_unsupported`, `scope_excluded` and `policy_conflict`.
Unknown spellings fail validation.

Findings must belong to this run and its frozen skill/rule/source versions.
This checks record attribution, not whether a quote, diff anchor or causal
argument is correct; those checks belong to later tickets. Recording a stage
does not execute it, and `completed` does not mean the code is proven correct.
This service saves configured budgets; [bounded investigation](investigation.md)
and the [model stage](model-review.md) enforce them at runtime.

The SQLite repository uses parameterized statements and one connection per
operation. Creation rejects duplicate run identities. Progress updates compare
the saved revision and parsed original inputs before committing, so a stale writer
receives `ReviewConflictError` rather than overwriting newer work. Restarting
the service reads the same inputs, results and event history. This ticket adds
no worker or automatic restart recovery.

Repository, PR number, head SHA, status and creation/update timestamps also have
query columns, with an index on `(repository, pull_request)`. Status and update
time change in the same transaction as progress. Query timestamps use UTC at
millisecond precision; the event payload retains its full timestamps.
Equivalent JSON formatting does not block progress or rewrite saved inputs.

## Explicit upgrade and local example

Migration `002_review_records.sql` adds the `review_runs` table;
`003_review_run_lookups.sql` adds and backfills its query columns. Back up existing
state and run `rush migrate` explicitly with the new image before starting it;
schema version is now 3. Migrations 001 and 002 are unchanged. No command silently creates
or migrates the review table. Follow [operations](operations.md) for backups.

This disposable example stores fictional inputs and leaves the record queued:

```sh
docker compose run --rm -T dev python - <<'PY'
import asyncio
from pathlib import Path
from app.core.settings import Settings
from app.dependencies import build_review_records, build_system
from app.schemas.review import ReviewInputs

async def main():
    settings = Settings()
    await build_system(settings).migrate()
    inputs = ReviewInputs.model_validate_json(
        Path("tests/fixtures/review-inputs.json").read_bytes()
    )
    record = await build_review_records(settings).create("demo-run", inputs)
    print(record.id, record.status)

asyncio.run(main())
PY
```

The example uses fabricated commit values and a fictional skill pin for storage
tests; it is not an installed skill or a real reviewed Git change. No provider
credentials or model calls are needed. The dev container's temporary state is
discarded with the container; normal app state remains in its persistent volume.
