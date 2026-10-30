# Local review

`rush review` reviews one committed change in a local Git repository with the
active [review skills](review-skills.md). It writes a readable summary and a
machine-readable report. It needs the Meta model and the review database, but
no running web service.

## Run it on a fictional example

This calls the live Meta model and can incur charges:

```sh
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev sh -ec '
  rush migrate
  example=$(sh scripts/reset-example.sh unsafe)
  context=tests/fixtures/customer_lookup/context
  rush review --repository "$example" --target fixture-base --head fixture-head \
    --ticket "$context/ticket.md" --guideline "$context/guideline.md" \
    --rules "$context/rules.json" --disclosure public --output reports/unsafe
'
```

The command prints the run ID, status, finding count and report paths. The
reports land in `reports/unsafe/` in your checkout; `reports/` is ignored by
Git.

[Recorded live results](local-review-evidence.json) show the safe, unsafe and
related examples producing their expected outcomes with all three starter
skills.

## Options

| Option | Meaning |
|---|---|
| `--repository PATH` | Local Git repository to review. Only committed objects are read. |
| `--target REV` or `--base REV` | Compare head with its shared starting point with the target (pull-request style), or with an exact version. |
| `--head REV` | Version to review. |
| `--ticket FILE` | Linked ticket text. |
| `--guideline FILE` | Approved guideline text. Can be repeated. |
| `--rules FILE` | Approved rules as a JSON list; each rule needs `id` and `version`. |
| `--disclosure` | Classification of the code and supplied files: `public`, `internal` or `private` (default). The team's approved list must allow it before anything is sent to the model. |
| `--skills PATH` | Approved skills folder. Default: `skills`. It must be outside the reviewed repository. |
| `--output DIR` | Report folder. Default: `reports/review`. |

Live retrieval of tickets and guidelines through MCP comes in TCR-011.

## What happens

1. The change is read and admitted within the review limits.
2. Active skills whose scope matches a changed file are selected. If none
   match, no model is called: the review is skipped, or partial if some files
   were omitted (too large, binary, or over the limits).
3. Each selected skill runs in turn through the
   [model stage](model-review.md). Skills share one investigation, so related
   reads and limits are shared too.
4. A separate critique pass judges every proposal: keep it, withdraw it, or turn
   it into an open question.
5. rush then checks each kept proposal itself. It is withdrawn if:
   - its line is unchanged context;
   - its file is outside the skill's scope;
   - its evidence does not quote the changed line it is anchored to;
   - it cites a rule the skill is not approved for;
   - it repeats another finding on the same line (one citing a rule is preferred).
6. The remaining proposals become findings. Each is marked as found by reading
   the code (`code_inspected`) and has a lasting fingerprint for later updates.

## Outcomes

| Status | Meaning | Exit code |
|---|---|---|
| `completed` | The configured review work finished within the reviewed scope. This does not prove the change correct or secure. | 0 |
| `partial` | Something that affects completeness is missing: omitted files, an exhausted limit, unavailable context such as a missing ticket, an unanswered investigation question, or a proposal no critique pass checked. Validated findings are still reported. | 0 |
| `skipped` | No active skill matches the changed files. | 0 |
| `failed` | The review could not run, for example invalid model output after one repair or a disclosure the team has not approved. | 1 |

Questions raised by the critique pass are listed as open questions that do not
affect completeness, and the summary headline says "with open questions". They
are never reported as findings.

If a skill asks to read related code but does not request read permission, the
refusal is noted without affecting completeness. If the team or runtime removes
read access a skill requested, the review is partial.

## Reports

`review.md` is the readable summary. For each finding it lists the location,
severity, category, problem, consequence, a triggering example, evidence,
suggested fix, rule and skill. It then lists limitations, related code read,
and withdrawn proposals with reasons.

`review.json` holds the same results with exact anchors, evidence references
(source, revision, hash, line range), fingerprints, limitations, related reads,
lifecycle events and model usage.

Both say that no application code or tests were run. rush never runs the
reviewed code or its tests, and never claims execution evidence.

## Limits

- Model judgment varies between runs; repeated runs can differ.
- Findings on the same changed line are merged. Two distinct problems on one
  line appear as one finding.
- Rule scope checks only confirm the rule is one the skill may apply. Checking
  a rule's own path and service scope comes with approved standards in
  TCR-012 + TCR-013.
- Unvalidated proposals from an incomplete run are counted in the report but
  never presented as findings.
- Withdrawn proposals and their reasons appear in the report files only; the
  stored review record keeps the final findings and limitations.
- Every model turn resends the supplied context and charges it against the
  source-size limit again, so more skills use more of that limit.
- A skill with no `rule_ids` may cite any supplied approved rule.
- `policy_sha` records the reviewed base commit; with `--rules`, the rules
  actually come from the supplied file, recorded as the `policy` source.
