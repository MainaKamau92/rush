# Bounded investigation

TCR-007 adds `InvestigationService`, assembled by `build_investigation()` in
`app/dependencies.py`. It admits a frozen change, verifies related-read requests
and records questions, snippets, refusals, counters and limitations. It needs no
server, database or model credentials.

## Host workflow

1. Build one service per investigation, optionally passing `ReviewLimits`.
2. Await `start(head, target=...)` or `start(head, base=...)` to discover and admit
   the change. Comparison semantics match [change reading](change-reading.md).
3. Register a change-specific question with `open_question(id, question, hunk_id)`.
   Its hunk must belong to the admitted scope. Questions are required by default;
   only the trusted host may explicitly mark a question optional.
4. Await `read(ReadRequest(...))`. Every request carries the registered question,
   originating hunk, relationship, target and expected evidence, plus a line
   window of at most 80 lines. A successful parent-read ID establishes the next
   dependency edge and its depth; clients cannot choose their depth.
5. Record `answer(question_id, answer, evidence_ids)` using that question's
   successful reads. Further reads for it are refused. Renaming an identical
   question does not reopen it. The host judges whether the answer resolves the
   question; the service does not evaluate its truth or deduplicate paraphrases.
6. Call `finish()` and inspect the report. Pending operations must finish before
   recording answers or finishing. No further work is allowed after finishing.
   `complete` describes context preparation, not a completed review or proof
   that submitted code is correct.

Reports contain the admitted `ChangeScope`, questions and attempted reads,
verified source path/range/object identity, target snippets at the frozen head,
counters, elapsed time and limitations. `report()` returns a snapshot without
closing the session. This service does not produce findings.

## Verified relationships

Reads use the repository provider and existing Git safeguards. They resolve a
regular file at the frozen commit, never the working tree, and do not follow
symlinks or submodules. No repository code, tests or installation scripts run.
Unsafe paths, missing entries, binary/non-UTF-8 content, oversized files and
unsupported links produce explicit refusals and leave required questions open.

The verifier statically parses Python; it does not import or execute it. It
supports module-level imports, direct imported/local calls, imported interface
or schema references, and literal configuration paths in `open()`/`Path()`.
It narrows the source to the changed function or requested parent snippet.
Shadowed/ambiguous imports, dynamic resolution and unsupported syntax/languages
do not count as proof. This is structural evidence, not a runtime call graph.

Caller/test links need an exact target already available or named in the host's
`search_paths`. This permits a bounded symbol check in that file, not a
repository crawl. The source function must be imported and called by the target.
Tests need a specific test relationship or an explicitly approved test path;
they still need a verified code link. There is no test quality or coverage audit.

When imports are outside the hunk, a scoped search reads only the named source
module and, for an approved incoming link, the exact candidate target. This
consumes the shared scoped-search budget and is audited. Target snippets are
delivered only after the edge verifies. Missing proof leaves an unresolved
question. Deletion-only origins cannot currently seed a head-side read.

## Budgets

Starting values come from `ReviewLimits`:

| Resource | Default |
|---|---:|
| Changed files / added plus removed lines | 20 / 500 |
| Additional files / snippet attempts | 8 / 16 |
| Relationship depth | 2 |
| MCP calls / scoped searches | 6 / 1 |
| Model calls, including retries | 12 |
| Source text | 128 KiB |
| Wall time | 180 seconds |

Initial discovery runs inside the wall deadline. Admission then applies file,
line and supplied-text limits before returning context. A file that does not
fit is wholly omitted with a `budget` reason; existing reader omissions remain
visible. The raw reader retains its separate 1 MiB per-file guard and may inspect
objects to discover changes before admission. The text budget is not a Git
disk-I/O quota.

Link verification fetches bounded module content and charges its full text,
but delivers only the requested snippet. Reusing a cached file avoids Git I/O
but still charges snippet/text use. Failed permitted attempts and retries
consume budgets. Unapproved, unproven targets are not read; approved incoming-link
candidates can be inspected during the scoped search.
Additional-file counts are unique paths; derived depth records the maximum.

`call_model(callback)` and `call_mcp(callback, scoped_search=False)` count each
host-supplied attempt and apply the remaining deadline. Future adapters must
use them for every retry. `supply_context(text)` charges additional approved
context, such as an MCP excerpt, before it is supplied. Provider token limits
are separate. The [model stage](model-review.md) uses the generation hook;
review-time MCP retrieval remains later work.

Required MCP/context exhaustion and changed-scope, model-call or wall-time
exhaustion make preparation incomplete. Extra-read/search/depth limits preserve
the unresolved question. Optional work can retain nonblocking limitations via
the trusted host's explicit `required=False`; source/model text cannot change
that decision. Provider errors and external cancellation propagate to the host,
which must record the failed/cancelled run. Provider timeouts do not themselves
exhaust the full review deadline.

## Disposable example

This executes the trusted fictional fixture reset helper, then inspects its
committed objects. It does not execute the inspected repository:

```sh
docker compose run --rm -T dev python - <<'PY'
import asyncio
from pathlib import Path
from app.dependencies import build_investigation
from app.schemas.investigation import ReadRequest

async def main():
    process = await asyncio.create_subprocess_exec(
        "sh", "scripts/reset-example.sh", "related", stdout=asyncio.subprocess.PIPE
    )
    output, _ = await process.communicate()
    if process.returncode:
        raise SystemExit(process.returncode)
    service = build_investigation(Path(output.decode().strip()))
    initial = await service.start("fixture-head", target="fixture-base")
    origin = initial.scope.files[0].hunks[0].id
    question = "Does the export helper restrict results to the caller tenant?"
    service.open_question("tenant", question, origin)
    result = await service.read(ReadRequest(
        question_id="tenant", question=question, origin_hunk_id=origin,
        relationship="callee", target="customer_store.py",
        expected_evidence="The query's tenant condition", start_line=1, end_line=14,
    ))
    if result.snippet:
        service.answer("tenant", "The export helper performs an unscoped query.",
                       (result.snippet.id,))
    report = service.finish()
    print("complete" if report.complete else "partial")
    print([item.path for item in report.reads if item.action == "read"])

asyncio.run(main())
PY
```

`rush change-read` remains a raw inspection command; it does not run this
workflow or model review. Runtime Git installation and remote PR acquisition
are unchanged. No database migration or new dependency is needed.
