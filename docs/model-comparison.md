# Meta comparison on the fictional corpus

These are live Meta calls using the same approved skills, instructions and
fictional examples. GitHub and ClickUp remain simulated. This is a small
automated matching exercise, not a general accuracy benchmark or human
acceptance/dismissal feedback.

## Full three-repeat comparison

[Full evidence](model-comparison-evidence.json) retains every case and failed
result, with deduplicated public source snapshots and the complete findings.
Each configuration ran the eleven declared skill/example pairs three times.

| Configuration | Matches / cases | Reported input tokens | Reported output tokens |
|---|---:|---:|---:|
| muse-spark-1.3 | 32 / 33 | 208329 | 19965 |
| muse-wonder-1.0 | 23 / 33 | 397224 | 24178 |

Both used adapter `0.2.0` and a 2048 output-token limit. Package, protocol,
corpus and implementation fingerprints are in the evidence. The fixed source
snapshot predates the final cached-learning approval guard; review instructions
and fixture packages were unchanged. The exact source archive is retained
locally under the ignored `reports/tcr024-live/` directory.

A preliminary run was interrupted when Docker stopped and its temporary
checkpoint disappeared. Its final outcome and usage are unknown and excluded
from these recorded totals. The separate bounded access check reported 14 input and
21 output tokens. No account charges or remaining credits were verified.

## Recheck and diagnosed limitations

The incomplete team-standards cohort was rechecked with question, read and
limitation details retained. This was an explicit subset, not a replacement or
an average that removes the earlier failures.

| Configuration | Matches / targeted cases | Reported input tokens | Reported output tokens |
|---|---:|---:|---:|
| muse-spark-1.3 | 7 / 9 | 63329 | 8817 |
| muse-wonder-1.0 | 0 / 9 | 242044 | 13799 |

[Recheck evidence](model-comparison-recheck.json) records all three repetitions
of unsafe, expired-exception and valid-exception for both configurations.
Observed problems include:

- Spark sometimes assigns the email-versus-name defect to the tenant-isolation
  rule. The extra finding fails the expected rule/category/location match.
- Wonder repeatedly requests `customers.py` as the `find_customer` callee even
  though the import names `customer_store.py`. The host refuses the unsupported
  relationship. The required question stays unanswered, and the review stays
  incomplete rather than silently widening permissions or claiming success.

The host constraints were preserved. These model-decision failures remain
visible; the evidence does not claim both configurations passed the suite.
The approved primary profile and activation records were not changed, and
there was no model fallback. Any prompt/protocol improvement should get a new
fingerprint and a separate full comparison, not overwrite these results.

## Reproduce

Use the commands in [local demo preparation](local-demo.md). The targeted
recheck command adds:

```sh
--skill rush.team-standards --case unsafe --case expired-exception --case valid-exception
```

The default remains a no-call plan; `--live` explicitly enables paid requests.
The latest runner also retains the configured per-call timeout and bounded-read
diagnostics. No skill activation evaluation is saved by the comparison runner.

Independent automated setup checks are recorded in
[fresh-setup evidence](fresh-setup-evidence.json). They used a clean tracked-source
snapshot without credentials or the internal wiki. This is automated
verification, not a human fresh-user or live GitHub/ClickUp acceptance claim.
