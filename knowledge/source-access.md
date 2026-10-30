---
type: Access Record
title: Source access
description: ClickUp MCP sources, discovered read tools, setup and reconnect steps, and live evidence for TCR-003.
status: draft
generated: {by: claude/claude-opus-5-5, at: "2026-10-30T04:30:00Z"}
sources:
  - id: backlog
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/mvp-backlog.md
    x_repo_path: docs/mvp-backlog.md
    x_sha256: 6d85883dbc12e4ab7f1c8a379d6e1d418d6fdd1e5927c294f0156b6669ce006c
  - id: scope
    resource: references/owner-source-scope-2026-10-29.md
  - id: credential-choice
    resource: references/owner-credential-choice-2026-10-30.md
  - id: evidence
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/source-access-evidence.json
    x_repo_path: docs/source-access-evidence.json
    x_sha256: a82bcd0f44d3169edf9aa353c69311f2f2e6e92a0fe8c54347b7f35c4a84aa69
  - id: service
    resource: https://github.com/MainaKamau92/rush/blob/main/app/services/source_access.py
    x_repo_path: app/services/source_access.py
    x_sha256: e793c83ee8e3cd465e749778a3b0f2a9b8df91224548766d566a0654cfd03f61
  - id: adapter
    resource: https://github.com/MainaKamau92/rush/blob/main/app/internal/adapters/clickup.py
    x_repo_path: app/internal/adapters/clickup.py
    x_sha256: 2602d8ad090df18f65c16ee6ec2c87fff6ffb09d284b17d91637fb4bf16d4310
  - id: auth
    resource: https://github.com/MainaKamau92/rush/blob/main/app/internal/adapters/mcp_auth.py
    x_repo_path: app/internal/adapters/mcp_auth.py
    x_sha256: fd436c47a95ca753bbeaf03635c3622eb8e3007d5884619c4efb15769b1fff61
  - id: clickup-mcp
    resource: https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server
  - id: clickup-tools
    resource: https://developer.clickup.com/docs/mcp-tools
  - id: clickup-auth
    resource: https://developer.clickup.com/docs/authentication
  - id: sdk
    resource: https://py.sdk.modelcontextprotocol.io/client/oauth-clients/
---
# Source access — TCR-003

TCR-003 proves rush can read one real ticket and one real guideline through
its own Python MCP client.[^backlog]

## Sources and approved resources

The owner chose **ClickUp only**: a ClickUp task is the ticket and a ClickUp
Doc page is the guideline. One workspace, one task and one Doc page are
approved. Their IDs stay in local configuration, never in this repository.[^scope]
The approved task is real project work linked from an owner-selected merged
PR, not a fictional demo item, so its content must not be published.

rush reads only references listed in `RUSH_APPROVED_TICKETS` and
`RUSH_APPROVED_GUIDELINES` (`DOCUMENT_ID/PAGE_ID`), and always sends the
approved `RUSH_CLICKUP_WORKSPACE_ID`. Anything else is refused before a
request is sent. A successful read is not permission to publish the content.

## Discovered tools

Live discovery listed 67 tools on 30 October 2026.[^evidence] rush maps only
two of them. Before each call it checks that the tool is listed, that its
required inputs are supplied, that no unlisted input is sent, and that the
server does not mark it as non-read-only or destructive.[^service][^adapter]

| Operation | Tool | Required inputs | rush also sends |
|---|---|---|---|
| `ticket.read` | `clickup_get_task` | `task_id` | `workspace_id` |
| `guideline.read` | `clickup_get_document_pages` | `document_id`, `page_ids` (list) | `workspace_id` |

Both tools carry `readOnlyHint: true`. That annotation is a hint, not trust.
The same listing also offers write and destructive tools such as
`clickup_delete_task` and `clickup_execute_operator`, which rush never
calls.[^clickup-tools] Retrieved text and tool descriptions are data; they
cannot change approvals, tools or reviewer settings.

## Credentials

| Method | Status |
|---|---|
| Personal token `CLICK_UP_API_TOKEN`, sent as `Bearer` | **Live verified.** Used for the reads below. |
| OAuth 2.1 + PKCE via `rush source-connect` | Fallback; controlled tests only, not run live. |

ClickUp's MCP FAQ says only OAuth is supported,[^clickup-mcp] but the server
accepted the owner's personal token as a bearer credential. The same token
without `Bearer` got HTTP 401. Treat this as undocumented behavior that ClickUp
could withdraw; OAuth remains the documented route.[^evidence] The owner chose
to keep the token and treat OAuth as an untested fallback.[^credential-choice] A personal token
carries the user's full read/write permission and cannot be narrowed to reads.
ClickUp states *"Personal tokens never expire"*, so no renewal is needed;
regenerating it in ClickUp settings replaces it.[^clickup-auth]

OAuth uses dynamic client registration at `https://mcp.clickup.com/oauth/register`,
a `http://localhost:8765/callback` redirect, PKCE `S256` and an `iss` check. ClickUp
advertises `read` and `write` scopes. The SDK would request both, so rush
narrows the authorization URL to `read`. ClickUp's metadata advertises only the
`authorization_code` grant, so refresh tokens may not be issued, and an expired
or revoked grant then needs `rush source-connect` again.

The official SDK (`mcp` 2.3.0) does not restore token expiry or discovered
metadata after a restart.[^sdk] Unattended commands therefore never start a
browser flow. With no stored sign-in they fail before any request; if the
server rejects a stored credential they stop with
`ClickUp authorization is required; run rush source-connect`. OAuth credentials
live in a named Docker volume as a `0600` file written atomically.[^auth]

## Connect and reconnect

Add to local `.env` (never commit): `RUSH_CLICKUP_WORKSPACE_ID`,
`RUSH_APPROVED_TICKETS`, `RUSH_APPROVED_GUIDELINES`, and either
`CLICK_UP_API_TOKEN` or nothing (to use OAuth).

```sh
docker compose build dev
docker compose -f compose.yaml -f compose.source-access.yaml run --rm dev rush source-connect
docker compose -f compose.yaml -f compose.source-access.yaml run --rm -T dev rush source-status
docker compose -f compose.yaml -f compose.source-access.yaml run --rm -T dev rush source-tools
docker compose -f compose.yaml -f compose.source-access.yaml run --rm -T dev rush source-read --kind ticket --reference TASK_ID
docker compose -f compose.yaml -f compose.source-access.yaml run --rm -T dev rush source-read --kind guideline --reference DOCUMENT_ID/PAGE_ID
```

With a token configured, `source-connect` just checks the connection. Without one
it prints a ClickUp address: approve read access, then paste the
`http://localhost:8765/callback?...` address the browser lands on into the
terminal prompt (the page itself will not load). To reconnect after revocation,
replace `CLICK_UP_API_TOKEN` or rerun `source-connect`. Outputs contain tool
names, hashes and lengths, never page text, IDs or credentials. Ordinary tests
and CI never use this override.

## Evidence

**Live, 30 October 2026**, rush's Python client in Docker:[^evidence]

| Check | Result |
|---|---|
| Tool discovery | 67 tools; both mapped tools present with matching inputs |
| Guideline read | `clickup_get_document_pages`, 1,274 characters, exit 0 |
| Ticket read | `clickup_get_task`, 15,003 characters, exit 0 |
| Unapproved reference | Refused, no request sent |
| Deliberately invalid token | `ClickUp rejected the configured credential…`, exit 1 |
| Deliberately invalid stored OAuth token | `ClickUp authorization is required…`, exit 1 |

**Controlled tests** (no network): OAuth sign-in with a ClickUp double that
mounts a real MCP server behind a bearer check (read-only scope, PKCE, private
storage, reuse without OAuth traffic, denied and forged redirects, rejected
credential); tool discovery and argument mapping over the MCP protocol; schema
drift; non-read-only refusal; timeouts, cancellation, rate limits; and safe
error messages.

## Limitations and blockers

- **[UNVERIFIED]** The OAuth fallback's live sign-in, granted scope, token
  lifetime and refresh behavior. Not required for TCR-003 by owner choice; run
  `source-connect` without a token before relying on it.
- No real credential was revoked. Revocation behavior is shown with
  deliberately invalid credentials against the live server.
- **[UNVERIFIED]** Whether regenerating a personal token invalidates the old one
  immediately; ClickUp's page does not say.
- **[UNVERIFIED]** That the approved task belongs to the approved workspace;
  ClickUp returned it for the token's user.
- Rate limits are per workspace and client on lower plans (100 tool calls per
  24 hours on Free Forever);[^clickup-mcp] the plan was not checked.
- One credential file per checkout; no lock across concurrent processes,
  matching the single-instance MVP.

The context broker, approved-guideline registry and review workflow belong to
later tickets. See [current work](current-state.md) and
[decisions](decisions.md).

[^backlog]: TCR-003 acceptance criteria.
[^scope]: Owner's source choice and disclosure rule.
[^credential-choice]: Owner kept the personal token; OAuth is a fallback.
[^evidence]: Sanitized live evidence; no IDs, page text or raw responses.
[^service]: Approval, discovery, schema and read-only checks.
[^adapter]: ClickUp tool mapping and error translation.
[^auth]: Credential storage, bearer and OAuth helpers.
[^clickup-mcp]: Endpoint, OAuth-only FAQ and rate limits, read 29 October 2026.
[^clickup-tools]: Published tool list, read 29 October 2026.
[^clickup-auth]: Personal token lifetime, read 30 October 2026.
[^sdk]: SDK OAuth client behavior, confirmed in the installed source.
