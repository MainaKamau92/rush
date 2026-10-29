---
type: Project
title: Purpose and scope
description: What rush is trying to build and what stays outside the MVP.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: prd
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/product-requirements.md
    x_repo_path: docs/product-requirements.md
    x_sha256: a1754495157192177d1e71d9330f1356fea73a37ee27d5cdbcecc382ec4f72e5
  - id: spec
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/technical-spec.md
    x_repo_path: docs/technical-spec.md
    x_sha256: d3c7ae1c574cad120ccc705d7924e54bc7a4aedd0a0599899a71dad6e7ccfa7f
---
# Purpose and scope

rush is intended to review a specific code change using approved team rules and
ticket context. Findings need evidence tied to the change. Related code reads
must answer a concrete question within limits. People can ask for clarification;
learning changes future behavior only after evaluation and approval.[^prd]

The MVP targets one repository and team, a small review skill set, a Meta primary
model and a second provider. GitHub comments and a CLI are the interface. Ticket
and guideline context comes through live MCP connections; ClickUp plus Notion is
the preferred pair, subject to access verification.[^spec]

Broad repository crawling, general coverage/test-quality audits, dedicated
security scanning, running reviewed applications, automatic fixes, and automatic
merging stay outside the MVP. Testing and quality gates for rush itself are
required.[^spec]

See [architecture](architecture.md) for implementation boundaries,
[decisions](decisions.md) for durable choices, and [current work](current-state.md)
for what actually exists. The PRD and current spec in `docs/` remain the detailed
requirements; `docs/archive/technical-spec-v0.2.md` is historical.

[^prd]: Product requirements.
[^spec]: Current technical specification.
