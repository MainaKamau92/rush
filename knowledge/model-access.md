---
type: Access Record
title: Model access
description: TCR-002's pending choices and safe live-test requirements.
status: draft
generated: {by: codex/unreported, at: "2026-10-29T09:23:11Z"}
sources:
  - id: backlog
    resource: https://github.com/MainaKamau92/rush/blob/main/docs/mvp-backlog.md
    x_repo_path: docs/mvp-backlog.md
    x_sha256: 5243a909862ac7b713288fee40f2cb06d25c40139bfccd55d6decb69226cfe9b
  - id: owner
    resource: references/owner-instructions-2026-10-29.md
---
# Model access — TCR-002

Status: paused for TCR-033. No live model request has been made for this ticket.

The owner chose Meta models and named `META_AI_KEY` in the local `.env`. The
issuing host has not been identified. Do not infer it from the variable name.
See [current work](current-state.md) before resuming.

The [ticket](https://github.com/MainaKamau92/rush/blob/main/docs/mvp-backlog.md#tcr-002--confirm-access-to-both-model-providers)
requires a successful Python request to a Meta model and a separate provider.
This access check does not implement the review workflow from TCR-008 or the
portability work from TCR-024.

## Decisions needed

| Item | Meta model | Second provider |
|---|---|---|
| Hosting provider and account | [UNVERIFIED] Awaiting selection | [UNVERIFIED] Awaiting selection |
| Exact model ID and endpoint | [UNVERIFIED] Awaiting selection | [UNVERIFIED] Awaiting selection |
| Credential variable or local secret file | `META_AI_KEY` in local `.env`, per owner | [UNVERIFIED] Awaiting setup |
| Account access and available credits | [UNVERIFIED] Not checked | [UNVERIFIED] Not checked |
| Usage charges and spending approval | [UNVERIFIED] Not checked | [UNVERIFIED] Not checked |
| Selected retention and training settings | [UNVERIFIED] Not checked | [UNVERIFIED] Not checked |
| Supported features and request limits | [UNVERIFIED] Not checked | [UNVERIFIED] Not checked |

Do not put credentials in this document, command arguments, test fixtures, or
saved request/response captures. Record credential locations or variable names
only. Account-specific settings need account evidence; public documentation
alone does not establish the settings selected for an account.

## Access check

Once the providers and spending permission are confirmed:

1. Verify the selected endpoint, authentication, model ID, request format,
   capabilities, limits, pricing, and data policy against official sources and
   the account settings. Keep unknown values explicitly marked.
2. Run a bounded request from Python through Docker using only the prompt
   `Reply with RUSH_OK.` No repository code or team documents are needed.
3. Record the time, code revision, configured and returned model identifiers,
   success or safe failure category, and reported usage when available. Omit
   credentials, headers, and raw provider responses.
4. Verify that unavailable models produce a clear failure without selecting
   another model, retrying on another tier, or changing data-handling settings.
   Exercise failure paths with controlled responses in ordinary CI.
5. Add the exact Docker command and credential setup instructions after the
   selected connections work. Keep live requests separate from required CI.

The ticket remains incomplete until both live requests succeed and the evidence
above is recorded. Do not describe access as confirmed on the basis of mocked
tests.
