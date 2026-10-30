# Review skills

A review skill is a small, versioned package of review instructions plus
examples that prove it works. rush runs only skills the team has approved,
whose files are unchanged since approval, and whose examples have passed with
the selected model.

## Starter skills

| Skill | Reports | Scope | Repository reads |
|---|---|---|---|
| `rush.team-standards` | Changed code that breaks an approved team rule. The finding cites the rule ID and version. | `**/*.py` | Yes |
| `rush.correctness` | Behavior defects the changed lines introduce, such as a wrong field or a broken condition. | `**/*.py` | Yes |
| `rush.ticket-intent` | Changes that do only part of what the linked ticket asks, or change what it says to leave alone. | `**` | No |

Architecture and compatibility problems fit within these skills; there are no
separate agents for them.

## Package format

Each package is a flat folder under `skills/` with exactly three files:

```text
skills/team-standards/
  manifest.json      identity, scope, permissions, model profile
  instructions.md    what the skill checks
  examples.json      acceptable and violating examples with expected results
```

`manifest.json`:

```json
{
  "schema_version": 1,
  "id": "rush.team-standards",
  "version": "0.1.0",
  "description": "Report changed code that breaks an approved team rule.",
  "scope": {"paths": ["**/*.py"]},
  "instructions": "instructions.md",
  "examples": "examples.json",
  "rule_ids": [],
  "permissions": {"capabilities": ["repo.read_snippet", "repo.find_symbol"]},
  "model_profile": "primary-meta"
}
```

- `scope.paths` are repository-relative globs. `*` matches within one folder
  and `**` across folders. A skill runs only when a changed file matches.
- `rule_ids` lists the approved rules a skill may cite: `["*"]` means any
  applied rule and an empty list means none. A skill with rule IDs must cite
  one in every finding.
- `permissions` requests capabilities; it cannot grant them. The effective set
  is the intersection of what rush supports, what the team approved, and what
  the skill requests.
- `model_profile` names a profile in the approved list.

`examples.json` names an example corpus and lists cases from it. A
`violating` case must expect at least one finding and an `acceptable` case must
expect none; each package needs both kinds. Findings match on rule ID and
version (or none), category, and changed location.

## Approval

`skills/approved.json` is the team's approved list. It records:

- the capabilities the team allows;
- which code and context classifications may be sent to the model
  (`allowed_disclosures`, `public` only by default);
- which source classifications may appear in reports for a public audience
  (`publishable_disclosures`, `public` only by default);
- the model profiles;
- each skill's package folder and content digest.

```json
{
  "schema_version": 1,
  "permissions": ["repo.read_snippet", "repo.find_symbol"],
  "allowed_disclosures": ["public"],
  "publishable_disclosures": ["public"],
  "model_profiles": {
    "primary-meta": {"model_id": "muse-spark-1.3", "adapter_version": "0.2.0", "max_output_tokens": 2048}
  },
  "skills": [
    {"id": "rush.team-standards", "version": "0.1.0", "package": "team-standards", "digest": "…"}
  ]
}
```

Approval happens through a reviewed change to this file on `main`. Skills come
from rush's own checkout, never from the repository under review, so a pull
request cannot change the skills or permissions used to review it.

rush refuses to load the approved list if any skill package:

- has a different digest from its approval, meaning its files changed;
- contains a link, a folder, an executable file, or any extra file;
- has an unknown manifest or example format, or a manifest whose ID or version
  differs from its approval;
- names files with path separators or `..`, or uses scope globs that escape the
  repository;
- requests a capability the team has not approved, or names an unknown model
  profile.

After editing a package, pin its new contents (this rewrites only its digest):

```sh
docker compose run --rm -T dev python scripts/approve_skill.py --skill rush.team-standards
```

## Activation by example evaluation

An approved skill stays inactive until a passing evaluation is recorded for:

- its exact digest;
- its profile's model, adapter version and output-token limit;
- rush's current review and critique protocol;
- every one of its examples.

Changing any of these makes the skill inactive again until a new evaluation
passes. Each case's recorded pass flag must agree with its recorded results, so
editing the file by hand cannot flip a failure to a pass.

The evaluation runs each example as a full local review with only that skill.
It uses the fictional customer-lookup corpus and the live Meta model, so it
costs money:

```sh
docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev \
  python scripts/evaluate_skills.py --save
```

Add `--skill ID` to evaluate one skill. Without `--save`, results are printed
but not recorded. A case passes only if:

- every expected finding is matched one to one;
- no extra or forbidden finding appears;
- expected limitations are present, and no other limitation affects completeness;
- no forbidden file is read;
- the review did not fail.

Results are written to `skills/evaluations/<id>@<version>.json`. They record
per-case results, model usage and a digest of the example corpus. Commit them
with the skill change.

Check what is installed without calling a model:

```sh
docker compose run --rm -T dev rush skill-list
```

## Limits

- One passing run activates a skill. The model's judgment varies between runs,
  so a pass is evidence, not a guarantee. TCR-024 + TCR-032 repeat the suite
  three times per model.
- The evaluation records a digest of the example corpus for audit, but
  activation does not recheck it, because the corpus lives in `tests/`. Re-run
  the evaluation after changing the corpus.
- Each skill is evaluated alone. A full review runs all matching skills, which
  share one set of limits, so it can hit a limit that a single-skill evaluation
  does not.
- One bad approved package stops every review, including `skill-list`, until
  it is fixed. This is deliberate: an unverifiable package never runs. Stray
  files such as `.DS_Store` count as extra files.
- Matching compares rule, category and location, not wording, so the meaning of
  each trigger still needs a human read.
- The example corpus is development data in `tests/`, so evaluation runs in the
  dev image.
