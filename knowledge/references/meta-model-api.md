---
type: Reference
title: Meta Model API
description: Official endpoint, request/storage semantics, models, and published pricing.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:59:28Z"}
sources:
  - id: reference
    resource: https://dev.meta.ai/docs/api-reference
  - id: schemas
    resource: https://dev.meta.ai/docs/api-reference/responses/schemas
  - id: models
    resource: https://dev.meta.ai/docs/models
  - id: pricing
    resource: https://dev.meta.ai/docs/pricing-rate-limits
  - id: authentication
    resource: https://dev.meta.ai/docs/authentication
---
# Meta Model API

Official docs identify `https://api.meta.ai/v1` with bearer authentication and
model listing and response-generation endpoints.[^reference] The Responses
schema supports explicit model selection, an output cap, reasoning settings,
and `store: false`; that flag controls retrievable response storage.[^schemas]

The model catalog lists Muse Spark and Muse Wonder for text/agentic work,
including structured output and tool capabilities.[^models] Standard and
Contributor model IDs select different training-use terms; prices and team rate
limits are published separately.[^pricing] The authentication guide covers key
creation, revocation, and rotation.[^authentication]

Read the sources again before relying on current availability or pricing.
These public documents do not confirm account credits, billing adjustments,
retention exceptions, or the correctness of future review output. See
[access evidence](../model-access.md) for what this project actually tested.

[^reference]: Official API resources and authentication.
[^schemas]: Request fields and response schema.
[^models]: Documented models and capabilities, not a rush feature claim.
[^pricing]: Standard/Contributor terms, prices, and published rate limits.
[^authentication]: Credential lifecycle.
