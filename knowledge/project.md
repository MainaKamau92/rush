---
type: Project
title: Purpose and scope
description: What rush is trying to build and what stays outside the MVP.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T17:52:29Z"}
sources:
  - id: prd
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/product-requirements.md
    x_repo_path: docs/product-requirements.md
    x_sha256: c72c333d1d7934080a009fe76260b78baff0e841a1cc512696a1166d3e135fae
  - id: spec
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/technical-spec.md
    x_repo_path: docs/technical-spec.md
    x_sha256: 7a36ab9ada2bca2b2b191709e93ffbc6a2f1115bbbd8d7e20805e682054928ba
---
# Purpose and scope

rush is intended to review a specific code change using approved team rules and
ticket context. Findings need evidence tied to the change. Related code reads
must answer a concrete question within limits. People can ask for clarification;
learning changes future behavior only after evaluation and approval.[^prd]

The MVP targets one repository and team, a small review skill set, and selected
Meta models behind a replaceable provider interface. Other providers are
deferred for the hackathon; testing Meta models does not establish cross-provider
compatibility. GitHub comments and a CLI are the interface. Ticket
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
