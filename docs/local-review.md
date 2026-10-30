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
    --rules "$context/rules.json" --approver "Ivo Reed" \
    --as-of 2026-01-15T12:00:00Z --disclosure public --output reports/unsafe
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
| `--ticket FILE` | Linked ticket text from a file. |
| `--guideline FILE` | Approved guideline text from a file. Can be repeated. |
| `--ticket-ref ID` | Approved ClickUp task to read live through MCP. Can be repeated. |
| `--pr-description FILE` | Pull request text. ClickUp task links in it (`https://app.clickup.com/t/...`) are read live. |
| `--live-guidelines` | Read every approved guideline page live through MCP. |
| `--audience` | `private` (default) or `public`. A public report withholds model-written text when the model saw sources that are not approved for publication. |
| `--rules FILE` | Approved team rules as a JSON list (format below). |
| `--exceptions FILE` | Approved exceptions as a JSON list (format below). |
| `--approver NAME` | A person whose approval activates rules and exceptions. Can be repeated. |
| `--as-of TIME` | Review time for rule and exception validity, ISO 8601 with a zone. Default: now. |
| `--allow-cached-policy` | Apply a rule's approved text even after its guideline changed, and say so. |
| `--disclosure` | Classification of the code and supplied files: `public`, `internal` or `private` (default). The team's approved list must allow it before anything is sent to the model. |
| `--skills PATH` | Approved skills folder. Default: `skills`. It must be outside the reviewed repository. |
| `--output DIR` | Report folder. Default: `reports/review`. |

## Team rules and exceptions

Rules, exceptions and the skills folder must sit outside the reviewed
repository, so a pull request cannot change the policy used to review it.
Tickets and guideline text never become rules; only the supplied rules file
does.

A rule looks like the fictional
[tenant rule](../tests/fixtures/customer_lookup/context/rules.json):

- **Identity and text:** `id`, `version`, `statement`, `rationale`, `category`.
- **Scope:** `scope.path` (a glob), with optional `scope.repository` and
  `scope.symbol`.
- **Flexibility:** `waivable` and `overridable`, plus an optional
  `overrides_rule_id`.
- **Approval:** `status`, `approved_by`, `approved_at`, optional `expires_at`.
- **Guideline link:** optional `source` (the guideline file name or
  `clickup:guideline:DOC/PAGE`) and `source_sha256` (the approved guideline's
  hash).

A rule applies only when all of these hold:

- its `status` is `approved` and `approved_by` is a listed `--approver`;
- it was approved before the review time and has not expired;
- its scope matches a changed file.

Supplying rules or exceptions without an `--approver` is an error.

Unapproved or expired rules are listed as `policy_not_applied`. The review is
then partial, because that standard was not checked, and guidelines linked to
those rules are not sent to the model. Only applicable rules are sent to the
model.

A finding is withdrawn when:

- its rule does not cover the finding's file;
- the skill may not cite that rule. A skill's `rule_ids` lists the rules it may
  cite: `["*"]` means any applied rule, and an empty list means none;
- it comes from a rule-citing skill (team standards) but cites no rule.

The SQLite record keeps the full applied rules and active exceptions, including
owners and approvals (`policy_record`), the review time, waived findings with
reasons, and every withdrawn proposal with its reason.

- **Overrides:** a narrower rule replaces a broader one only when it names it
  in `overrides_rule_id` and the broader rule is `overridable`. Findings under
  the broader rule are then withdrawn for files in the narrower rule's scope.
  The narrower rule must use a different path pattern that falls inside the
  broader rule's scope for the changed files. Any other override claim is a
  `policy_conflict` that makes the review partial.
- **Contradictions:** when two rules contradict each other without an override,
  the team-standards skill reports `policy_conflict` instead of choosing one.
  rush then withdraws findings under any rule named in that conflict.
- **Changed guidelines:** if a supplied guideline no longer matches a rule's
  `source_sha256`, the new text is not sent to the model. The rule is then
  either not applied (`guideline_changed`, partial) or, with
  `--allow-cached-policy`, applied from its approved text with a disclosed
  `guideline_changed` note.

An exception, like the fictional
[waiver](../tests/fixtures/customer_lookup/context/valid-exception.json), has:

- `id`;
- the exact `rule` ID and version;
- `scope`;
- `allowed_condition` and `rationale`;
- `owner` and `approver`;
- `approved_at` and optional `expires_at`;
- `status`.

An exception is active only when all of these hold:

- its approver is listed;
- it is current at the review time;
- it names the rule's current version;
- the rule is waivable.

The model never sees exceptions, so it cannot skip a violation. After
validation, rush moves a finding to `waived` only when all of these match:

- the exception's exact rule and version;
- the rule's category;
- the exception's path;
- if the exception names a `scope.symbol`, the enclosing function or class. rush
  confirms it from the changed code; if it can't, nothing is waived and this is
  noted.

The waived entry records which exception applied, its owner, approver and
reason. rush does not verify the free-text `allowed_condition`, and the waived
reason says so. A later repeat of the same line is withdrawn rather than kept. Other findings,
such as a wrong return value on the same change, stay. Expired, unauthorized,
outdated-version and non-waivable exceptions are listed as `policy_not_applied`.

[Recorded live results](policy-review-evidence.json) cover the valid-exception,
expired-exception and conflicting-rules examples.

## Live tickets and guidelines

Live reads use the ClickUp connection from
[source access](operations.md#clickup-source-access-checks) and its override:

```sh
docker compose -f compose.yaml -f compose.model-access.yaml -f compose.source-access.yaml \
  run --rm -T dev sh -ec '
  rush migrate
  example=$(sh scripts/reset-example.sh unsafe)
  printf "Closes https://app.clickup.com/t/TASK_ID\n" > /tmp/pr.md
  rush review --repository "$example" --target fixture-base --head fixture-head \
    --pr-description /tmp/pr.md --live-guidelines \
    --rules tests/fixtures/customer_lookup/context/rules.json --output reports/live
'
```

Replace `TASK_ID` with an approved task. This calls ClickUp and Meta.

- **Where links come from:** ticket links come only from the pull request
  text or an explicit `--ticket-ref`. Guidelines come only from
  `RUSH_APPROVED_GUIDELINES`. Links inside retrieved tickets are never followed.
- **What is read:** only approved tasks and pages are read, always in the
  approved workspace, and only with the two verified read-only tools. Links to
  other hosts or look-alike addresses are ignored. Links to another ClickUp
  workspace and unapproved links are recorded as `access_denied` without any
  request.
- **What is kept:** structured responses are reduced to the text a review
  needs (task name and description, or page names and content), capped at
  32,000 characters, so assignees and other people fields are dropped. A
  structured response rush does not recognize is refused rather than stored.
  Plain-text responses are kept as returned. The record stores the link,
  workspace, passage, content hash and retrieval time.
- **Versions:** a version is recorded only when ClickUp states one: a page's
  `version`, or a task's `date_updated` (recorded as `date_updated:<value>`).
  Retrieval time is never used as a version.
- **Limits:** reads count against the review's MCP-call and time limits.
- **No sign-in:** a review never waits for someone to sign in. Expired or
  rejected credentials become `access_denied`, with the reconnect step.
- **No search:** rush does not search ClickUp. A ticket mentioned only by name
  or custom ID stays unresolved and is reported as `missing_ticket`; give its
  link instead.

| Situation | Limitation | Affects completeness |
|---|---|---|
| No ticket link and no `--ticket` file | `missing_ticket` | Yes |
| Several tickets read | `conflicting_sources` (all are used) | No |
| Link not approved or in another workspace; credential missing, expired or rejected (HTTP 401/403) | `access_denied` | Yes |
| ClickUp text classified more strictly than the model may receive (nothing is read) | `access_denied` | Yes |
| ClickUp rate limit, including HTTP 429 (remaining reads are skipped) | `rate_limited` | Yes |
| Tool error, empty or unrecognized response, connection failure, no approved guideline | `missing_context` | Yes |
| Text longer than the cap | `content_truncated` | Yes |
| MCP-call limit reached | `budget` plus `missing_context` | Yes |

## Disclosure

Set `RUSH_SOURCE_DISCLOSURE` to the classification of the ClickUp workspace
(`private` by default). Code and context reach the model only when
`allowed_disclosures` in `skills/approved.json` includes their classification.
If live sources are classified more strictly than that, rush does not read
them at all, and the review is partial with `access_denied`. Supplied files
share the code's classification (`--disclosure`).

Reading a source is not permission to publish it. For `--audience public`, if
the code or any source the model saw is outside `publishable_disclosures`,
every model-written sentence is withheld: finding text, open questions, read
questions, paths the model asked for but was refused, and limitation reasons. Locations, severities, categories and rules stay visible,
and the private record keeps everything. Ticket, guideline and code text
cannot change permissions, model settings, rules or destinations; it reaches
the model only as data.

## What happens

1. The change is read and admitted within the review limits. If the request
   asks for live context and a skill will run, approved tickets and guidelines
   are then read through MCP.
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
- A rule's `scope.symbol` is passed to the model but not checked by rush;
  scope is enforced by repository and path.
- Approvers are names supplied by the local operator. GitHub identity checks
  come with the GitHub stages.
- Unvalidated proposals from an incomplete run are counted in the report but
  never presented as findings.
- Withdrawn proposals and their reasons appear in the report files only; the
  stored review record keeps the final findings and limitations.
- Every model turn resends the supplied context and charges it against the
  source-size limit again, so more skills use more of that limit.
- A skill with no `rule_ids` may cite any supplied approved rule.
- Live ClickUp reads were tested against a protocol double. The real response
  shapes of task and page reads have not yet been checked live for this
  feature.
- The public-audience check is used by the local report today. Pull request
  comments and replies (TCR-017 onward) must use the same `DisclosureService`.
- `policy_sha` records the reviewed base commit; with `--rules`, the rules
  actually come from the supplied file, recorded as the `policy` source.
