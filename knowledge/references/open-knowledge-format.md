---
type: Reference
title: Open Knowledge Format
description: Canonical specification and format choice.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: blog
    resource: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
    title: Google Cloud introduction
  - id: migration
    resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf
    title: Old location and migration notice
  - id: spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/0b87c52c6ef999286c745e19998fdfcd03d5dbee/SPEC.md
    title: Canonical OKF 0.2 specification at the inspected revision
---
# Open Knowledge Format

The supplied Google article introduces OKF using Markdown and YAML metadata.[^blog]
Its old repository location now redirects readers to a dedicated canonical
repository and labels the old copy frozen.[^migration]

This bundle targets the inspected OKF 0.2 specification: concepts have typed
frontmatter; indexes and logs have reserved roles; sources and generation
metadata describe provenance; normal links connect concepts. Our project lint
rules add required navigation and source checks without claiming to implement
every optional format feature.[^spec]

The root index declares the version. See [maintenance](../maintenance.md) for
the local rules. Review future format changes explicitly rather than silently
following the moving main branch.

[^blog]: Owner-supplied introduction.
[^migration]: Migration notice in the old location.
[^spec]: Pinned canonical specification, read during setup.
