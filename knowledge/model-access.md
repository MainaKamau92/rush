---
type: Access Record
title: Model access
description: Meta access evidence, safe live-check commands, and account unknowns.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T10:08:04Z"}
sources:
  - id: backlog
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/mvp-backlog.md
    x_repo_path: docs/mvp-backlog.md
    x_sha256: 6d85883dbc12e4ab7f1c8a379d6e1d418d6fdd1e5927c294f0156b6669ce006c
  - id: owner
    resource: references/owner-model-scope-2026-10-29.md
  - id: meta
    resource: references/meta-model-api.md
  - id: settings
    resource: https://github.com/MainaKamau92/rush/blob/main/app/core/settings.py
    x_repo_path: app/core/settings.py
    x_sha256: 961da7fa49fa8e0f7d2284de7f0f3b54774b3271316d902c9ef753f209bb2794
  - id: service
    resource: https://github.com/MainaKamau92/rush/blob/main/app/services/model_access.py
    x_repo_path: app/services/model_access.py
    x_sha256: 07d8568b03b51c5c23d5eb8a1dceae1b5bb4c6e9273b17b224eefd58761a0924
  - id: adapter
    resource: https://github.com/MainaKamau92/rush/blob/main/app/internal/adapters/meta.py
    x_repo_path: app/internal/adapters/meta.py
    x_sha256: 13eeb548c30f8bbb8432829db12726f79a7b8079c72058b950a6f474903c0967
  - id: models
    resource: https://dev.meta.ai/docs/models
  - id: pricing
    resource: https://dev.meta.ai/docs/pricing-rate-limits
  - id: evidence
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/model-access-evidence.json
    x_repo_path: docs/model-access-evidence.json
    x_sha256: c45a0ad6e1d6445f8f6dac13bf94995f327cf45cac9993e7c3e41aa7b9a728f8
---
# Model access — TCR-002

The owner chose Meta Model API, confirmed `https://dev.meta.ai/api-keys` as the
issuing site, authorized small paid tests, and deferred other providers for the
hackathon.[^owner] Preserve provider-neutral service boundaries, but do not
describe two Meta models as cross-provider verification.

## Live evidence

Recorded on 29 October 2026 from the TCR-002 working tree, using Python through
Docker and the actual `rush model-check` command. Both checks required the
model to return exactly `RUSH_OK`; the raw responses were not saved.[^evidence]

| Explicit requested ID | Returned ID | Result | Input / output / total tokens |
|---|---|---|---|
| `muse-spark-1.3` | `muse-spark-1.3` | Available, exit 0 | 14 / 24 / 38 |
| `muse-wonder-1.0` | `muse-wonder-1.0` | Available, exit 0 | 14 / 77 / 91 |
| `rush-unavailable-model` | None | Clear unavailable-model error, exit 1 | Not reported |

An authenticated model listing also succeeded. Both successful responses
reported limits of 3,000 requests/minute and 4,000,000 tokens/minute in the
allowlisted rate-limit headers. These are observations, not guaranteed future
quotas or money balances.[^evidence]

## Connection and reproducible check

Keep `META_AI_KEY` in local `.env` or an equivalent protected secret injection.
Do not rename the owner's accessor or paste the key into commands. The official
API uses bearer authentication at `https://api.meta.ai/v1`; rush uses
`POST /responses`.[^meta]

```sh
docker compose build dev
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev rush model-check --model muse-spark-1.3
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev rush model-check --model muse-wonder-1.0
```

The separate override opts into credential forwarding. Do not use it for the
normal test suite or untrusted PRs. Required CI uses controlled responses and
no live keys. The access check needs no migration or running HTTP service.
Rotate/revoke keys in the issuing dashboard and update the local secret.

Each check sends only `Reply with RUSH_OK.`, caps output plus reasoning at
128 tokens, requests minimal reasoning and `store: false`, and uses a total
deadline of 30 seconds by default. There is one generation request, no retry,
redirect, model fallback, or provider fallback. Contributor model IDs are
rejected before a request. CLI output includes identity and usage, not the
model's text, credentials, arbitrary headers, or raw errors.

## Features, price, and data handling

The docs list a 1,048,576-token context window and native tool/structured-output
capabilities for both selected models.[^models] This ticket proves only bounded
text access. Large context, review tools, skill fixtures, and task-specific
quality have not been tested here; they belong to later tickets. Exact backend
weight revisions were not captured by these checks and remain **[UNVERIFIED]**.

| Standard-mode model | Published input price / 1M tokens | Published output price / 1M tokens |
|---|---|---|
| `muse-spark-1.3` | $1.25 | $4.25 |
| `muse-wonder-1.0` | $4.00 | $20.00 |

These are published rates checked on 29 October 2026, not invoice totals or
promised credits; caching/account terms can affect charges.[^pricing] The docs
state Standard-mode content is not used for model training. The tested IDs
select Standard mode; no Contributor variant is enabled. `store: false` requests
non-persistence for later Responses retrieval, not zero provider retention.

| Account detail | State |
|---|---|
| Available credits / remaining money balance | **[UNVERIFIED]** Account dashboard balance not confirmed. |
| Actual charges / discounts | **[UNVERIFIED]** No invoice or billing export inspected. |
| Retention / zero-retention entitlement | **[UNVERIFIED]** Not established by the public docs or these calls. |
| Undocumented account limits or exceptions | **[UNVERIFIED]** Only the observed headers and published defaults are recorded. |
| Another provider | Deferred by owner; no credentials or live compatibility claimed. |

## Boundaries and next work

`ModelAccessService` depends on `TextModelProvider`; the Meta adapter translates
HTTP responses and is assembled with HTTPX only in `app/dependencies.py`.
Tests verify injected substitutes work without Meta-specific business logic,
but do not prove another vendor's protocol. Per-task model configuration and
real review comparisons remain in TCR-008/TCR-024. No provider/tier/data-mode
switch may occur silently.

See [current work](current-state.md) for PR/review status before starting another
ticket. Unknown account details remain explicit; a successful access check is
not evidence that the reviewer workflow has been built.

[^backlog]: Updated ticket scope and acceptance criteria.
[^owner]: Latest owner model choice and spending permission.
[^meta]: Official API/authentication/request semantics.
[^models]: Documented capabilities, not stress-tested account limits.
[^pricing]: Published Standard-mode pricing and data-use terms.
[^evidence]: Safe recorded live-check outputs; no raw response bodies or keys.
