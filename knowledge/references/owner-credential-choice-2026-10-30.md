---
type: Source Record
title: ClickUp credential choice
description: Owner's decision to use the personal token for ClickUp MCP access and treat OAuth as an untested fallback.
status: draft
generated: {by: claude/claude-opus-5-5, at: "2026-10-30T07:30:00Z"}
sources:
  - id: conversation
    resource: Owner's reply to Claude's question about the live OAuth check on 30 October 2026
---
# ClickUp credential choice

Conversation summary recorded on 30 October 2026; no transcript retained.[^conversation]

- The owner supplied a ClickUp personal token as `CLICK_UP_API_TOKEN` and chose
  to keep using it for rush's ClickUp MCP access.
- The live interactive OAuth sign-in is not required for TCR-003. OAuth stays
  in the code as a fallback with controlled tests only.
- Claude explained the trade-offs first: ClickUp documents MCP as OAuth-only,
  so token acceptance could be withdrawn, and a personal token carries the
  user's full read/write permission.

[^conversation]: Owner's answer: "let's stick with the token".
