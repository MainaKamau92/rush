---
type: Evaluation Fixtures
title: Fictional customer lookup examples
description: Repeatable local demo inputs, expected outcomes, and verification limits.
status: draft
generated: {by: codex/unreported, at: "2026-10-30T11:53:24Z"}
sources:
  - id: backlog
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/mvp-backlog.md
    x_repo_path: docs/mvp-backlog.md
    x_sha256: 6d85883dbc12e4ab7f1c8a379d6e1d418d6fdd1e5927c294f0156b6669ce006c
  - id: guide
    resource: https://github.com/MainaKamau92/rush/blob/main/tests/fixtures/customer_lookup/README.md
    x_repo_path: tests/fixtures/customer_lookup/README.md
    x_sha256: c345719ae8f511f6716ed77e31600424745e6d0a4ed6a06b7d5a9b8737353f9e
  - id: cases
    resource: https://github.com/MainaKamau92/rush/blob/main/tests/fixtures/customer_lookup/cases.json
    x_repo_path: tests/fixtures/customer_lookup/cases.json
    x_sha256: ef42c04d9800fc352843f7e093ef56e0b61338f7591aa652af407e568fdcb8e9
  - id: reset
    resource: https://github.com/MainaKamau92/rush/blob/main/scripts/reset-example.sh
    x_repo_path: scripts/reset-example.sh
    x_sha256: fe5a0520b5ee661cddf10955633efe77bb91c149610f32ab74f92f0a8cd77b3c
---
# Fictional examples — TCR-004

Lantern Cart is a fictional team with customer-lookup code, a linked ticket,
approved tenant-ID guideline and scoped exceptions. No private ClickUp source
is reused. The corpus is local development data, not a skill manifest.[^guide]

Eight cases cover A01 unsafe, A02 safe with an unrelated defect, A03 required
dependency inspection, A05 unavailable context, A06 injected instructions and
unapproved policy edits, A07 valid/expired exceptions, and A08 policy conflict.
Each records rule/category/anchor/trigger expectations, forbidden findings and
reads, limitations, source snapshots and frozen review time. The waiver permits
only its named tenant rule; returning an email instead of a name remains an
independent correctness finding.[^cases]

## Reset and verify

```sh
docker compose run --rm -T dev sh -ec '
  example=$(sh scripts/reset-example.sh unsafe)
  git -C "$example" diff fixture-base fixture-head
'
docker compose run --rm -T dev pytest -q tests/integration/test_examples.py
```

The script creates a fresh temporary repository in the same container, never
deletes an existing checkout, and restores deterministic `fixture-base` and
`fixture-head` tags. Context snapshots remain outside the candidate repository.
Use the path within that invocation; removing the container discards it.[^reset]

## Limits

Expected review outcomes are authored expectations, not model results or proof
of reviewer enforcement. This ticket adds no review engine, model calls, skill
format, live retrieval or ClickUp writes. A04 live fictional sources require
separate owner approval before creating anything externally.[^guide]
The later evaluator should match findings one-to-one using rule identity,
category, anchor and trigger meaning, independently checking limitations and
read/permission boundaries.[^guide]

[^backlog]: TCR-004 acceptance criteria and scope.
[^guide]: Corpus structure, matching rubric and limitations.
[^cases]: Exact expected outcomes for each fictional case.
[^reset]: Disposable Git repository construction and fixed commit identity.
