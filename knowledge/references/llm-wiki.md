---
type: Reference
title: LLM Wiki
description: The source/wiki/instruction pattern supplied by the owner.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: gist
    resource: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    title: LLM Wiki by Andrej Karpathy
---
# LLM Wiki

The supplied pattern separates original sources, maintained Markdown synthesis,
and agent instructions. It recommends linked topic pages, an index, a change
log, and regular checks for contradictions and stale information.[^gist]

Our adaptation uses existing project documents as canonical sources and this
bundle as the maintained synthesis. AGENTS.md defines when to read and update
it. The [maintenance playbook](../maintenance.md) makes this part of normal work.
No search server or optional visualization tool is needed for the starting set.

This page is a summary, not a mirrored copy of the gist. Revisit the source when
the maintenance approach changes.

[^gist]: Owner-supplied original gist, read during setup.
