# Verifying the PR review journey locally

`tests/e2e/test_pr_journey.py` runs the main user journey against the real
service:
- the FastAPI app and its review worker;
- SQLite;
- bare Git mirrors fetched from a Git remote;
- change reading, skills, policy, validation and publication.

For now the parts outside our control are simulated:
- **GitHub REST API:** a stateful simulation of PRs, comments, check runs and
  permissions.
- **ClickUp MCP:** a source that serves the fixture ticket and guideline.
- **Meta model:** a scripted stand-in that follows the review protocol.

Run it, and save fresh evidence, with:

```sh
docker compose run --rm -T -e RUSH_JOURNEY_EVIDENCE=/workspace/docs/pr-journey-evidence.json dev pytest -q tests/e2e/test_pr_journey.py
```

The last recorded run is in [pr-journey-evidence.json](pr-journey-evidence.json).

## What the journey checks

| Step | Expected | Evidence key |
|---|---|---|
| Open the unsafe example PR with its linked ticket | The ticket (from the PR description) and the approved guideline go through the live retrieval path, against the simulated source. One finding under `lantern.tenant-lookup@1` on `customers.py` line 5 cites the changed line, the ticket's tenant lines, the guideline's rule text and the related store code, and explains the consequence and the fix. The advisory check is `neutral`, and the published comment is saved. | `initial` |
| Related-file inspection | Every read has a reason and a direct relationship (a `callee` of the changed hunk). `billing.py`, with its existing defect, is not read or reported. | `context_reads` |
| Ask for an unrelated file | A request for `billing.py` is refused and recorded as `denied`. The defect there is not reported, and the unanswered question keeps that review `partial`. | `unrelated_read` |
| Open the safe example PR | No finding; the check is `success`. | `safe` |
| Repeat the same delivery and send `/rush review` | The repeat is ignored. The rerun edits the same inline comment. A summary whose response was lost (GitHub saved it, then returned 502) is found again rather than posted twice; the post and summary counts are measured. | `repeats` |
| Push a fix | The finding is rechecked and its comment marked resolved, with no new comments; the check is `success`. | `corrected` |
| Push during a review | The review of the old head finds the problem but is `superseded`. Nothing is published for it, and the check on that commit is unchanged. | `push_during_review` |
| Restart with one active and one queued job | The active run is recorded as cancelled, never successful. Its job is queued again and finishes on its second attempt as `partial` (that PR has no ticket, so `missing_ticket`). The new inline comment's response is lost and the comment is found again. The queued job runs once. | `recovery` |

The restart here is graceful: shutdown cancels the worker. After a hard kill,
the run is left `running`, and recovery marks it failed on the next start; the
review job tests cover that case.

## Still to do with real services

The same steps are to be repeated near the end with:
- the owner's GitHub App, forwarding and demo repository (see
  [GitHub reviews](github-reviews.md));
- live ClickUp MCP with the approved ticket and guideline;
- the live Meta model.

Until then, these steps are verified only against simulations, and nothing here
claims a live result.
