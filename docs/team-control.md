# Verify team control, honesty and safety locally

TCR-029 + TCR-030 uses `tests/e2e/test_team_control.py`, a sibling of the
[PR journey](pr-journey.md). It reuses that journey's simulated GitHub, scripted
model, signed events and temporary Git repositories. The app, worker, SQLite,
review services, skills, policy and publication run locally. GitHub, ClickUp
and Meta responses are simulated; no live provider credentials are needed.

Run the scenarios and regenerate their sanitized observations:

```sh
docker compose run --rm -T \
  -e RUSH_CONTROL_EVIDENCE=/workspace/docs/team-control-evidence.json \
  dev pytest tests/e2e/test_team_control.py -q
```

[Recorded observations](team-control-evidence.json) contain statuses, limitation
codes and counts, without source passages, model replies or private records.
The test assertions establish the checks below; the observations alone are
not a substitute for a passing test run.

| Acceptance | Local evidence |
|---|---|
| A11: understand and correct | All plain/technical × short/detailed wording combinations preserve the stored record, including nonempty limitations; replies retain severity, evidence and conclusion. A deliberately false finding on safe code is challenged, withdrawn with a citation to the tenant-bearing call, and recorded in thread history. |
| A09–A10: control learning | A proposal and an evaluated proposal have no effect on later reviews. Untested, unauthorized and stale-hash approvals fail. An authorized approval makes the exact revised rule appear in a later review. |
| A07: bounded exceptions | A valid waiver suppresses its tenant violation while an unrelated correctness finding remains. Expired, old-rule-version and other-function waivers leave both findings visible. |
| A05, A08, A15: honest limits | Denied/missing tickets, exhausted context budget, changed wiki content and an invalid policy override produce incomplete reviews and advisory neutral checks. An unsupported cross-service candidate becomes an unresolved question after critique, with missing context still blocking completion. |
| A06: host authority | Instructions in each PR/ticket/wiki location are paired with hostile model responses: an arbitrary destination, settings changes, an unapproved rule or an unrelated read. Host rules, model selection and permissions stay fixed; no forbidden destination or source is requested. A read-only collaborator's rerun is skipped. |
| A14: no application testing | Reports explicitly record that application tests were not executed; repository access remains bounded reads. These scenarios test rush itself. |
| A16: disclosure | Private canaries stay in the internal review record and are withheld from public findings, waiver reasons, Markdown/JSON reports, checks, explanations, reassessment replies and captured app logs. |

The scenarios exposed two product defects that are fixed here: public waiver
reasons now pass through disclosure withholding, and explanation/reassessment
responses must come from the selected provider/model, complete successfully,
match any pinned revision and use no unsupported features. Invalid responses
leave the finding unchanged.

## Limits of this evidence

Scripted responses prove host controls and workflow behavior, not whether a live
model detects bad instructions or reasons correctly. They do not verify live
GitHub permissions, ClickUp response shapes, Meta quality or private data
handling by those services.

The learning scenario injects an evaluator that performs actual local reviews
of the proposal's unsafe and safe examples with the scripted model, then stores
their results through the normal learning service. It does not claim that the
CLI's built-in evaluation passed. That evaluator also labels the skill's
exception/conflict cases acceptable, but does not supply their fixture policy
context. In this corpus, unsafe and conflicting-rule code can be identical;
this can reject a legitimate proposal. It fails closed, and needs correction
before relying on that evaluator for the live demo. No evaluation or approval
gate is bypassed or relaxed by these tests.
