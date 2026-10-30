# Model review stage

TCR-008 connects the existing model provider to the prepared
[bounded investigation](investigation.md). It supports a selected Meta model
through `ModelReviewService`, assembled by `build_model_review()` in
`app/dependencies.py`. TCR-009 + TCR-010 run several skill tasks in one stage,
add a critique pass, and turn proposals into findings; see
[local review](local-review.md). MCP context retrieval remains TCR-011.

## Run the fictional protocol check

This explicitly uses live Meta requests and can incur charges. It sends only
the public fictional customer example and its supplied ticket/guideline, with
at most four generation attempts and 2,048 output tokens per attempt:

```sh
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev \
  python scripts/check_model_review.py --model muse-spark-1.3 --case related
```

Choose `safe`, `unsafe` or `related`. Select the model explicitly; no substitute
model, provider or Contributor tier is selected on failure. `META_AI_KEY` stays
in the existing local configuration. Normal tests and CI do not use this
override or live credentials.

The helper resets the trusted fictional fixture and explicitly migrates a fresh
temporary database. Its output contains stage status, selected/resolved model
metadata, usage, response hashes, counts and related paths, without raw model
responses or source passages. It is a protocol exercise, not an installed skill
evaluation or a general local review command.
See [sanitized live evidence](model-review-evidence.json) for the recorded run
and preliminary checks; the successful stage has not passed semantic critique.

## Host integration

1. Prepare one investigation at the frozen head/base, using the limits from the
   intended `ReviewInputs.settings`. The host owns this broker exclusively until
   the model service finishes it.
2. Build `ReviewInputs` from that exact scope, including its manifest hash,
   selected review model/adapter version, approved source snapshots and skill
   pins. The service rejects mismatched SHAs, limits, scope, model or task pins.
3. Supply one `ReviewTask` per skill, each with trusted instructions and a
   different frozen skill reference, all with the same code disclosure. Tasks
   run in order against the same investigation. If the settings include a
   `critique` model, a critique pass then judges every proposal. The caller must obtain these from trusted configuration; this
   ticket does not load or verify a skill package from the reviewed repository.
4. Supply runtime, repository and skill permission lists. The effective set is
   their intersection. This implementation requires both `repo.read_snippet`
   and `repo.find_symbol` for related code reads; they grant neither arbitrary
   file access nor another repository. The broker still verifies every edge.
5. Set the code's disclosure classification. Private is the default; the allowed
   disclosure list defaults to public only. The host must explicitly authorize
   other classifications before code or source excerpts can reach the model.
6. Apply database migrations explicitly, then build the model service with the
   configured settings and prepared investigation. Await
   `service.run(run_id, inputs, *tasks)` once, and always await `service.close()`
   in `finally` to release its HTTP client.

The current Meta adapter version is `0.2.0`. It offers text JSON through the
shared provider contract; native tool calls and native schema enforcement are
disabled in rush. Capability flags describe the adapter's implemented surface,
not what Meta's server could support. Unassessed token limits and unavailable
backend revisions remain `null`. Required unsupported features fail before a
generation attempt. When a backend revision becomes available, it is recorded
and must remain the same for later calls in that stage.

## Model protocol

`app/schemas/model_review.py` generates the response JSON Schema from Pydantic.
The permitted responses are:

| Kind | Host behavior |
|---|---|
| `request_context` | Validate permissions and each question/read request, then use the bounded broker. At most 16 requests per response. |
| `candidates` | Check basic diff anchors, known rule versions and selected source IDs/ranges, then retain up to 32 unvalidated proposals. |
| `done` | Stop the model stage and retain explicit limitations; this does not assert that a review is complete. |

Each response may answer prior questions using successful `read_id` values.
Answers cannot cite invented reads or another question's evidence. Missing
answers leave required questions unresolved even if the model says `done`.
Model limitations always affect completeness; the model cannot downgrade them
with a flag or change host permissions.

The input contains the admitted change, approved excerpts, evidence catalog,
read refusals/results, questions and effective permissions. Evidence catalog
entries supply exact source IDs. The model selects only those IDs and line
ranges; the host attaches frozen revisions/hashes rather than asking the model
to reproduce them. Ranges are relative to the supplied passage; diff passages
list the hunk's lines in order. Related snippets
retain the frozen head and original file range. No model-provided URL or tool
name is executed. MCP retrieval belongs to TCR-011.
Frozen source metadata without a supplied passage creates an explicit context
limitation rather than an assumption about the page's contents.

Trusted instructions and the generated schema are sent separately from this
untrusted input using Meta's developer-priority `instructions` field, as
documented in the [Responses API](https://dev.meta.ai/docs/protocols/responses#setting-instructions).
Every request uses `store: false` and no native tools. Repository/source text
does not gain authority by appearing in the input.

## Limits and outcomes

All generation attempts, including a schema repair, use the investigation's
shared model-call count and remaining wall deadline. Previously supplied source
text is charged again when resent on another turn. Each call also has the
configured provider timeout. A per-call timeout fails the stage; exhausting the
shared budget returns partial work. External cancellation stops work, saves a
cancelled record and propagates to the caller.

Each skill task, and the critique pass, gets at most one schema-repair attempt. Repeated
invalid JSON or an unknown/extra action fails explicitly. Identity mismatch,
incomplete generation, transport failure and unsupported native output stop
without repair or fallback. Responses are capped at 1 MiB before parsing.

The existing review record now retains optional proposed findings, captured
context, capabilities, model attempts, an instruction hash and usage. Every
attempt records identity, status and available token counts; raw response/error
bodies are not stored. If any attempt's usage is unknown, aggregate token counts
stay unknown. Existing record data remains readable; no SQL migration is added.

| Stage result | Saved review state |
|---|---|
| `ready` | `validating`: the model stage finished, with proposals awaiting semantic/evidence review. |
| `partial` | `partial`, with omitted scope, refused context or unresolved work. |
| `failed` | `failed`, including persistent schema errors; never a successful empty review. |
| External cancellation | `cancelled`, then task cancellation propagates. |

Proposals are distinct from canonical findings. The record service refuses
publication/completion while unvalidated proposals remain. The critique pass and
the host checks described in [local review](local-review.md) decide which
proposals become findings. No application tests execute, and no GitHub
publisher or automatic approval is present here.

## Critique pass

When the settings include a `critique` model, every proposal is sent back with
the quoted lines of its evidence. The critique returns exactly one verdict per
proposal: `keep`, `withdraw` (unsupported, pre-existing, style-only, relying
on tests that never ran, or repeating another proposal), or `question` with
the open question. It cannot add findings. It uses the shared model-call count
and deadline, and its own single schema repair.

Each evidence catalog entry includes a numbered copy of its passage, so the
model can cite exact line ranges without counting lines itself.
