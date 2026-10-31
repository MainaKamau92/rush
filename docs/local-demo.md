# Local demo preparation

**Status: implementation and fictional-data verification.** GitHub and ClickUp
remain simulated by owner choice. The [live Meta comparison](model-comparison.md)
is recorded, including failed and incomplete cases; it is not an all-pass
quality claim. The [plan](model-comparison-plan.json) remains a no-call command
preview. No real-source integrated demo or completed video is claimed, and
TCR-024 + TCR-032 final acceptance remains open.

The [automated rehearsal record](demo-rehearsal-evidence.json) captures a fresh
run of both assembled journeys. Its elapsed time measures test execution,
not the duration of a presenter delivering the storyboard.

## Start from a fresh checkout

Docker Compose is the development and demo workflow. No host Python environment
or credentials are needed for the simulated rehearsal:

```sh
git clone https://github.com/MainaKamau92/rush.git
cd rush
docker compose build dev
docker compose run --rm -T dev rush --help
docker compose run --rm -T dev pytest -q tests/e2e/test_pr_journey.py tests/e2e/test_team_control.py
docker compose run --rm -T dev python scripts/compare_models.py --output /tmp/comparison-plan.json
```

The last command creates a plan inside its disposable container. To keep the
plan, use an output under `/workspace`, the mounted checkout. Use the existing
[PR journey](pr-journey.md) and [team-control](team-control.md) commands when
regenerating their tracked, sanitized evidence files. Fresh clones do not need
the internal `knowledge/` folder.

## Model comparison

The selected configurations are `muse-spark-1.3` and `muse-wonder-1.0`, each with
adapter version `0.2.0` and an output limit of `2048`. The runner uses the same
approved package pins, instructions, examples and host review pipeline for both.
Only the selected skill's model profile changes for this evaluation. It does
not rewrite instructions, change the approved catalog, activate a model/skill
combination or save activation evaluations.

Plan without calling a model:

```sh
docker compose run --rm -T dev python scripts/compare_models.py \
  --output docs/model-comparison-plan.json
```

**After explicit authorization to enable live Meta calls**, supply `META_AI_KEY`
only through the existing Compose override and run:

```sh
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev \
  python scripts/compare_models.py --live --output /workspace/model-comparison.json
```

That command makes paid calls. It runs every configured skill/example pair
three times per model, with fresh fictional repositories and temporary SQLite
state. Each result includes expected and actual rule/category/anchor matches,
misses, unexpected and forbidden findings, forbidden reads, limitations,
response-attempt status, elapsed time and available token usage. Findings and
their public fictional source snapshots are retained for human review after
temporary state is removed. Automated matching checks rule/category/location
and limitations, not the truth of the explanation or its trigger scenario;
inspect that text and evidence separately. The runner refuses to retain
non-public sources. Inspect the resulting artifact before publishing it.
Exceptions
remain individual failures, without raw provider error text or hidden retries.
Completed failures are retained; cancellation leaves an incomplete checkpoint.
An unsuccessful comparison exits nonzero. Do not publish a checkpoint as a
completed run or infer general model accuracy from this small corpus.

Run the permission/approval/attribution/publication controls separately for
each repetition; preserve every failed run before fixing and rerunning it:

```sh
docker compose run --rm -T dev pytest -q \
  tests/e2e/test_pr_journey.py tests/e2e/test_team_control.py
```

Those controls use scripted model responses. Their results must stay separate
from the live model measurements and from human acceptance/dismissal feedback.
No human feedback has been collected by the comparison runner.

## Live setup still required

The setup paths are documented in the [README](../README.md#endpoints-and-commands),
[GitHub reviews](github-reviews.md) and
[team learning](team-learning.md). Before the live rehearsal:

1. Enable live services with the owner; use fictional, approved demo data only.
2. Configure Meta through the existing `META_AI_KEY` accessor.
3. Configure the ClickUp workspace, approved ticket and guideline IDs and its
   credential in local `.env`. Read the approved passages through MCP; do not
   substitute private project tickets into public evidence.
4. Create/install the GitHub App on the demo repository, store its key outside
   the checkout, configure the webhook secret and approve local event forwarding.
   Use the Docker-only webhook proxy/tunnel in the forwarding guide. Its local
   signed-body smoke test passes; the external GitHub/tunnel round trip remains
   deferred until active integration testing.
5. Provide operator-owned approved rules/exceptions outside the reviewed
   repository; set the authorized approvers and disclosure classes. Apply
   migrations explicitly and keep the state volume.
6. Use the corrected built-in learning evaluator, with explicit labels for every
   affected skill example. Reevaluate older cached proposals before approval;
   see [team learning](team-learning.md).
7. Run and retain the live comparison and live PR journey. Record any remaining
   policy-conflict/ticket-intent deviation instead of silently changing the
   expected outcome.

## Three-minute storyboard

During a simulated rehearsal, keep **SIMULATED: scripted GitHub, ClickUp and
model responses** visible. If using a saved evidence file rather than executing
the service during the presentation, also label it **PRERECORDED OUTPUT**.

| Time | Show | Evidence or live action |
|---|---|---|
| 0:00–0:20 | rush running locally; name the simulated/live boundaries | Docker test invocation or local app health; no hosted deployment claim |
| 0:20–0:55 | Unsafe lookup, linked ticket and approved guideline | PR journey initial finding with change attribution and citations |
| 0:55–1:15 | Necessary dependency read; unrelated file refused | `customer_store.py` read and denied `billing.py` evidence |
| 1:15–1:35 | Plain explanation and corrected false positive | Wording invariance and evidence-backed withdrawal from team-control scenarios |
| 1:35–1:55 | Valid exception suppresses only its intended issue | Tenant waiver plus remaining email/name correctness finding |
| 1:55–2:20 | Inactive proposal, evaluation and exact authorized approval | Learning lifecycle before/after; label the scripted model during simulations |
| 2:20–2:40 | Second model with the same pinned examples | Actual comparison report when available; otherwise explicitly show **NOT RUN**, never a synthetic quality ranking |
| 2:40–3:00 | Missing context stays incomplete; state remaining limits | Neutral advisory check, missing-context limitation and outstanding evidence |

This storyboard is not a recorded video or an independently timed rehearsal.
The live sequence needs rehearsal after the services are enabled.

## Sharing and acceptance

Before sharing a recording, inspect the actual frames and audio for credentials,
local `.env` contents, account IDs and private source material. Inspect generated
reports separately; this preparation does not claim a nonexistent video passed
a privacy check. Verify that the intended audience can access the repository and
any video, and confirm contributor names/handles and credit requirements with
the owner. Keep secrets and the internal wiki out of the published artifacts.

| Check | Current evidence | Remaining work |
|---|---|---|
| A01–A03, A12, A14 | [Simulated PR journey](pr-journey.md) | Repeat with the live services |
| A04 | Retrieval path simulated in the PR journey; historical access checks in source-access docs | Live fictional demo ticket/guideline retrieval |
| A05–A11, A15–A16 | [Simulated team controls](team-control.md) | Live explanation/reassessment and learning quality checks |
| A13 | [Live comparison and targeted recheck](model-comparison.md), same pinned skills and three repetitions | Resolve or accept the recorded model-decision limitations; no all-pass quality claim |
| Fresh-user setup | [Independent automated setup and shared state](fresh-setup-evidence.json); [local webhook forwarding](webhook-forwarding-evidence.json) | Human/live setup attempt and external forwarding round trip |
| Video, access and contributors | Storyboard and sharing checklist | Record, inspect and verify the actual deliverables |

Automated observations and authored expectations are not human acceptance.
Unfinished rows do not constitute MVP sign-off.
