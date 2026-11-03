# GitHub reviews on the local service

rush is used mainly as a GitHub App. For the MVP, the FastAPI service runs on
your own machine through Docker Compose, and GitHub events are forwarded to it.
There is no hosted deployment.

When a PR opens, reopens or gets new commits, rush stores a review job and then
acknowledges the event. A worker inside the service reviews jobs one at a time:

1. It reads the PR again from GitHub.
2. It copies the head and target commits into a bare local mirror.
3. It reviews them with the same change reader, skills and policy as
   `rush review`.

The service never checks out or runs PR code. The result is then published on
the PR (see [Publishing on the PR](#publishing-on-the-pr)), and job progress is
shown at `/jobs`.

## Create the GitHub App

Create the app under the account or organization that owns the demo repository:
**Settings → Developer settings → GitHub Apps → New GitHub App**.

| Setting | Value |
|---|---|
| Webhook URL | Your forwarding URL (see below) |
| Webhook secret | A long random value, e.g. from `openssl rand -hex 32`; put it in `.env` |
| Repository permissions | Metadata: read-only, Contents: read-only, Issues: read-only, Pull requests: read and write, Checks: read and write |
| Subscribe to events | Pull request, Issue comment, Pull request review comment |
| Where can it be installed | Only on this account |

Grant nothing else. In particular, don't grant Administration or write access to
Contents: without them the app can't merge, push or change branch protection.
rush uses:

- **Pull requests write** for review comments (TCR-017).
- **Checks write** for the advisory check (TCR-019).
- **Metadata read** to look up a commenter's current permission.
- **Issues read**, which GitHub requires before an app can receive comment
  events, including `/rush review` on a PR.

After you create the app:

1. Note its App ID.
2. Generate a private key and keep the `.pem` file **outside this checkout**.
3. Install the app on the demo repository only.

Never commit the key or the webhook secret. If either leaks, regenerate it in
the app settings and update `.env`.

## Forward events to your machine

For Docker-only forwarding, use the pinned Cloudflare client behind the
webhook-only Caddy proxy in `compose.forwarding.yaml`. After configuring the
GitHub App settings below:

```sh
docker compose -f compose.yaml -f compose.github.yaml -f compose.forwarding.yaml --profile forwarding up -d --build --wait app webhook-proxy
docker compose -f compose.yaml -f compose.github.yaml -f compose.forwarding.yaml --profile forwarding up -d forwarder
docker compose -f compose.yaml -f compose.github.yaml -f compose.forwarding.yaml logs forwarder
```

Set the app's webhook URL to the generated HTTPS address followed by
`/github/webhook`. This is an ephemeral quick tunnel for local development;
keep its address out of public recordings and stop it when finished. The
proxy forwards only `POST /github/webhook`; `/jobs`, `/health` and other paths
return 404 through the tunnel. It preserves the original body and signature
headers; rush still verifies the HMAC before accepting an event.

The [local forwarding smoke evidence](webhook-forwarding-evidence.json) checks
an indented Unicode body signed with a fictional secret, a tampered body and
blocked routes through real local containers. It does not claim a public
Cloudflare/GitHub round trip has run. The proxy runs without capabilities;
its image removes the upstream binary's unnecessary low-port file capability
because it listens on 8080.

The former Smee recipe is withdrawn: the inspected
[Smee client](https://github.com/probot/smee-client/blob/master/index.ts)
serializes the parsed JSON body again, which can invalidate a signature over
the original bytes. Do not work around this by disabling signature validation.

Stop just forwarding without deleting application state:

```sh
docker compose -f compose.yaml -f compose.github.yaml -f compose.forwarding.yaml stop forwarder webhook-proxy
```

## Configure and start

Fill in the GitHub section of your local `.env` (see `.env.example`):

| Setting | Meaning |
|---|---|
| `RUSH_GITHUB_APP_ID` | The app's numeric ID. |
| `RUSH_GITHUB_PRIVATE_KEY_PATH` | Host path to the downloaded `.pem`, outside the checkout. Compose mounts it as a secret; the service runs as user 10001, which must be able to read it (on Linux, for example, `chmod 644` inside a private directory). |
| `RUSH_GITHUB_WEBHOOK_SECRET` | The webhook secret set on the app. |
| `RUSH_GITHUB_REPOSITORIES` | `OWNER/NAME` of each repository rush may review, comma-separated. Events from others are refused. |
| `RUSH_REVIEW_DISCLOSURE` | Classification of the reviewed code: `public`, `internal` or `private` (default). `skills/approved.json` must allow it before code reaches the model. |
| `RUSH_TEAM_POLICY_DIR` | Host folder holding approved rules and exceptions, mounted read-only at `/policy/team`. |
| `RUSH_REVIEW_RULES_FILE` / `RUSH_REVIEW_EXCEPTIONS_FILE` | Container paths such as `/policy/team/rules.json`. Leave them empty to review without team rules. |
| `RUSH_REVIEW_APPROVERS` | People whose approval activates rules and exceptions, comma-separated. |

`META_AI_KEY` is required as well. ClickUp settings are optional. When
`RUSH_CLICKUP_WORKSPACE_ID` and `CLICK_UP_API_TOKEN` are set:
- up to three ClickUp tasks linked in the PR description are read live, as
  with `rush review --pr-description`; no ticket list is needed, but tasks in
  another workspace are refused;
- the approved guidelines (`RUSH_APPROVED_GUIDELINES`) are read live for every
  PR.

A PR whose description links no ticket is still reviewed in full; the summary
shows a one-line note (`missing_ticket`) and the review is not marked incomplete.
An unreachable ClickUp server makes the review partial;
missing credentials make the job fail with a clear reason.

Skills, rules and exceptions come from this checkout and the policy folder,
never from the PR under review. Rule scopes match the repository as
`owner/name`.

```sh
docker compose build app
docker compose run --rm app rush migrate
docker compose -f compose.yaml -f compose.github.yaml up -d --wait app
```

Back up state before running the migration on an existing database; see
[operations](operations.md#build-release-run). Without the GitHub settings, the
service starts normally and `/github/webhook` and `/jobs` return 404.

## What starts a review

| Event | Result |
|---|---|
| PR opened, reopened or synchronized | A job for that head commit. A newer commit supersedes queued jobs for older ones. |
| A PR comment with `@rush-reviewer`, `@rush-reviewer review` or `/rush review` | A rerun job. Before reviewing, the worker checks the commenter's **current** repository permission; without write, maintain or admin access, the job is skipped and says why. |
| Any event from a bot, including rush itself | Ignored, so rush can't trigger itself. |
| A repeated delivery ID, or the same signed event resent | Acknowledged and ignored. |
| App installation events | Acknowledged and ignored. |
| An unsigned or wrongly signed event | Rejected with 401 before anything is read or stored. |
| An event type other than PR and comment events (except `ping`) | Rejected with 422. |
| An event from a repository not listed | Rejected with 403. |

`RUSH_GITHUB_MENTION` changes the mention alias (default `rush-reviewer`). The app's
own slug, fetched with its authenticated `GET /app`, also works with or without
`[bot]`, for example `@rush-team-app review` or `@rush-team-app[bot]`.
Quoted lines (`>`) and code spans or fenced blocks never start commands.
Bot comments remain ignored; mentioning the app grants no additional permission.

Only one job per PR version can be queued or running. A command that arrives
while a review is pending points to that job instead of starting another.

Before review starts, a job is skipped (with its reason) when:

- the PR is closed;
- the PR targets another repository;
- the PR moved to a newer commit;
- a rerun was requested without write access.

If the PR's target commit has left its branch, for example after a force push,
the job fails with a reason asking you to update the PR and comment
`/rush review`.

## Progress, failures and restarts

`GET /jobs?limit=20`, `GET /jobs/JOB_ID` and `docker compose run --rm app rush jobs`
show each job's:

- status: `queued`, `running`, `completed`, `partial`, `failed`, `skipped` or
  `superseded`;
- reason;
- attempts;
- review run ID.

Reasons are fixed messages and never include tokens, keys, the webhook secret or
PR text. Unexpected errors show only the error type; details go to the service
log.

Jobs are saved in SQLite before GitHub receives its acknowledgement. If the
service stops during a review, that run is marked failed on the next start and
its job is queued again, unless a newer review of the same PR is already
waiting. The single worker means the same PR is never reviewed twice at once.
A job interrupted three times is marked failed instead of retried. If the
worker loses access to its state, it logs the error, requeues its own job and
keeps running.

Every delivery is recorded for duplicate checks, and the MVP never prunes these
records.

Mirrors live under `/state/repositories` in the state volume. They hold only
fetched Git objects, with no working tree.

## Review scope and batches

Noise is intentionally excluded before it consumes file, line or source budget.
`RUSH_REVIEW_IGNORE` is a comma-separated glob list. Defaults cover lockfiles,
package-manager locks, common images/fonts, minified JS/CSS, source maps, and
`dist`, `build` and `generated` assets. Binary content detected while reading is
also intentionally excluded. The summary discloses each excluded path once in
a collapsed list; intentional exclusions alone do not make a review partial.
Unreadable source, oversized passages and unfinished review work remain real
limitations. Renaming a source file into an ignored path does not hide its
change unless both paths are excluded.

Application source is scheduled before tests, then low-priority files. Within
those groups, larger changes come first, with stable path ordering for ties.
`RUSH_REVIEW_LOW_PRIORITY` defaults to `docs/**`, `knowledge/**`, `**/*.md` and
`**/verification/**`; documentation JSON is covered by `docs/**`. Either glob
list can be replaced, or explicitly set empty. Reviewed repositories cannot
change these operator settings.

| Setting | Default | Maximum | Bound |
|---|---:|---:|---|
| `RUSH_REVIEW_MAX_FILES` | 20 | 500 | Files per batch |
| `RUSH_REVIEW_MAX_CHANGED_LINES` | 1000 | 10000 | Added plus removed lines per batch |
| `RUSH_REVIEW_SOURCE_BYTES` | 131072 | 4194304 | Source payload bytes per model call |
| `RUSH_REVIEW_MAX_MODEL_CALLS` | 60 | 500 | Entire review, including critique and repairs |
| `RUSH_REVIEW_WALL_SECONDS` | 1800 | 7200 | Entire review, including discovery and context reads |

To review a large pull request in a single batch, raise the file and line
limits above its size and set `RUSH_REVIEW_SOURCE_BYTES` to at least twice its
packed diff size. Raise `RUSH_MODEL_TIMEOUT_SECONDS` and `RUSH_REVIEW_WALL_SECONDS`
too, because each call then carries the whole diff and several calls run per
review. For example, a 37-file, 2,600-line change packs to about 780 KB and fits
in one batch at 4194304 bytes, with a 600-second timeout and a 7200-second wall.
Every investigation round resends the batch, so token use grows with the batch
size. The single review worker is busy for the whole review, and the timeout also
bounds connection attempts and thread replies.

The frozen record inputs retain these limits. Batch packing reserves half of
the source allowance for follow-up reads, critique and envelope overhead, and
the complete payload is checked before a call. Ticket, guideline and policy
passages have a separate 65536-byte payload allowance; they go to each batch
without reducing its code allowance. Oversized context is reported explicitly,
not silently trimmed. GitHub reviews also have review-wide caps of 24 additional
files, 64 snippet attempts and 24 scoped searches, with relationship depth 2.
These bounded multi-file allowances replace the one-search local-fixture default;
they are also frozen into the record. MCP calls remain capped at 6.

Large hunks are partitioned with stable fragment identities and original line
numbers. Each batch runs the skills whose approved file scopes apply; rule-only
skills need an applicable frozen approved rule. Their absence is reported
neutrally: "No approved team rule applies to these files." Host validation,
critique, rule authority, waivers and disclosure still apply before findings
from all batches are merged into one review record and publication.

The record's `batches` list names their paths, model-call counts and completion
state. If the call or time cap stops a review, unfinished files are named and
the outcome stays partial. Earlier critiqued findings can still be published;
uncritiqued proposals cannot. CLI reports distinguish reviewed and unfinished
files. No application code or tests are executed.

## Publishing on the PR

Each run reviews the whole PR again; earlier results are not reused. The
worker reads the PR again before publishing, and again before resolving earlier
findings and before writing the summary and check. If a newer commit has
arrived, publishing stops and the job is marked `superseded`. A failure report
is also skipped when the head has moved. Only the current
version receives the current outcome.

| What | How it stays current |
|---|---|
| One summary comment | Found again by its hidden `rush:summary` marker and edited in place. |
| One inline comment per finding, on the changed line (new or deleted) | Keyed by the finding's lasting fingerprint plus its occurrence number, for identical lines. A later run that reports the same finding edits that comment instead of adding another. |
| Findings GitHub cannot place on a line | Kept as a short finding line in the summary; publication problems are disclosed and the full review record retains the detail. |
| Earlier findings no longer reported | Marked **Resolved** only after a *complete* review of a *newer commit* rechecked them. After an incomplete review, or an explicit exclusion of their file, they stay open; the summary states how many were not rechecked. A rerun on the same commit that does not repeat a finding also leaves it open, because model recall varies between runs; the summary counts these and the check stays neutral. Each finding comment carries a hidden marker naming the commit it was last reported on; older comments fall back to the commit GitHub recorded when they were posted. |
| The advisory check `rush review` on the head commit | Created once per commit, then updated. |

Comments are edited, never deleted, so replies in their threads are kept. rush
only edits comments written by its own app account. Model-written text is
neutralized before posting: HTML is escaped, `@` mentions don't notify anyone,
and image links don't load. All inline comments are published first through
`POST /pulls/{n}/comments`, including `start_line`/`line` ranges when their frozen
changed-line evidence supports a range. The summary is written afterward, with
counts and one short line per finding linking to its returned `html_url`.
Limitations are grouped and deduplicated in one collapsed block in plain
language; ignored or skipped files have a separate collapsed block. The check
uses the same summary. The advisory line says that no code or tests were run.
The summary is capped below GitHub's size limit.
A finding no longer reported on a newer commit may have been fixed, waived by
an approved exception, or withdrawn; the note says so. On the same commit, only a
waiver in this run or an earlier withdrawal after a challenge resolves it. If it recurs, the existing thread is
reopened and its earlier resolution/reassessment notes remain visible. Older
reassessment decisions stay attached to their recorded run.

Every planned comment is saved in the `publications` table (migration 005)
before it is sent. If GitHub's response is uncertain (no reply, a 5xx, or no comment ID), rush
first looks for the comment's marker and posts again only if the comment did
not appear. This prevents duplicates in the usual case; a comment list that
lags behind GitHub could still let one through.

The summary and check keep these apart:

- findings;
- missing context;
- exhausted limits;
- policy problems;
- execution errors;
- publication problems.

| Check conclusion | When |
|---|---|
| `success` | The review was complete, found nothing, and everything was published. |
| `neutral` | There are findings, the review was incomplete or skipped, or some results could not be published. An incomplete review is never `success`. |
| `failure` | The review could not run. The reason is in the check and the summary. |

The check is advisory: rush never changes branch protection or required checks.
`RUSH_GITHUB_AUDIENCE` (default `public`) controls whether model-written text
that drew on sources not approved for publishing is withheld, as with
`rush review --audience public`.

## Questions, decisions and challenges

Initial inline comments and explanation replies share the team defaults
`RUSH_EXPLAIN_COMPLEXITY=plain` and `RUSH_EXPLAIN_VERBOSITY=short`.
Override either for a new review with:

```text
/rush review complexity=technical verbosity=detailed
```

Options belong on the first line and accept only `plain|technical` and
`short|detailed`. A queued review keeps its settings; wait for it to finish
before requesting another with different options. Automatic reviews use the
team defaults. Settings are saved with the review, and replies inherit them
unless their own command overrides them. Changing team defaults requires
recreating the app container through the normal Docker Compose workflow.

Rewording uses the Meta model after validation, with the remaining review call
and time allowance. It can change explanatory prose, while the host preserves
severity, rule, evidence and review status. Short comments keep the problem,
connection, consequence and fix visible, with example and evidence expandable.
If rewording fails or the budget is exhausted, the original validated finding
is retained and the summary discloses the fallback. This optional wording pass
does not turn a completed analysis into an incomplete one.

Reply in a finding's review thread with one of these commands on the first
line. Only people with write, maintain or admin access can use them; rush
checks the commenter's current permission each time.

| Command | What happens |
|---|---|
| `/rush explain [simpler\|technical\|example\|evidence\|change] [complexity=plain\|technical] [verbosity=short\|detailed] [question]` | The Meta model rewords the finding with the requested focus. |
| `/rush accept [reason]` | The acceptance is recorded with the actor. |
| `/rush dismiss <reason>` | The dismissal is recorded with the actor and reason. |
| `/rush challenge <reason>` | rush reassesses the finding from its recorded evidence. |
| `/rush learn <rule text> because <reason>` | Creates an inactive team-learning proposal from the finding (see [team learning](team-learning.md)). |
| `/rush approve-learning <proposal> <hash>` | A designated approver activates the exact evaluated version. |

Every command above also accepts the configured mention alias or the app's
own mention: for example `@rush-reviewer explain simpler` or `@rush-team-app challenge
<reason>`. The same permission and exact-approval checks apply. Quoted/code
commands are ignored, while code quoted in a valid command's arguments is kept.

**Explanations**
- Complexity and verbosity are separate settings. The team defaults are
  `RUSH_EXPLAIN_COMPLEXITY` (`plain` or `technical`) and
  `RUSH_EXPLAIN_VERBOSITY` (`short` or `detailed`). A request can override
  either one over the review's frozen settings; `simpler` and `technical` also set the complexity unless it is
  given explicitly.
- rush writes the severity, rule, evidence, limitations and conclusion itself,
  so rewording can't change them. The model only supplies the problem, the link
  to the change, the consequence and the requested answer, and even a short
  answer has all three.
- Model text is neutralized as in other comments.
- With a public audience (`RUSH_GITHUB_AUDIENCE`), a finding whose text is
  withheld is not explained either.

**Decisions**
- Acceptance and dismissal are recorded only. They never create or change a
  team rule, and a dismissal is not treated as proof the finding was wrong.

**Challenges**
- The model receives only the finding, the numbered excerpts of the sources it
  cites (a window around the cited lines, with their original numbers,
  including its diff hunk), and the challenge text, treated as a claim.
  This is one bounded call with one repair attempt.
- **Keeping or amending** a finding needs citations that exist in those
  excerpts; otherwise the result counts as inconclusive. Invented evidence is
  never used to defend a finding.
- **Recovery:** if the service stops mid-command, the job runs again and its
  reply may appear twice.
- **Every verdict needs support:** keep, amend and withdraw all need citations
  that exist in the excerpts, and an amendment can't raise the severity.
- **Withdrawn or amended findings:** rush adds one note block to the original
  comment, keeping the original text. A later challenge replaces that note, and
  later re-publishing keeps it.
- **Later commands:** commands on a withdrawn or resolved finding are refused.
  Explanations use the amended form of an amended finding.
- **Summary and check:** these change only at the next review, which checks
  the code again independently.
- **Inconclusive results:** the finding stays unchanged and the reply asks for a
  human decision.

Every command, verdict and before/after state is stored in the
`finding_events` table (migration 006) with the actor and time. The next full
review checks the code again independently.

## Review formatting

Inline comments lead with severity, location and a concise explanation, followed
by a clearly separated suggested fix. Identifiers and paths use inline code;
multiline code uses language-tagged fences. Short comments fold evidence and
examples below the explanation. Summaries link the findings and list reviewed
paths separately from skipped or incomplete paths. Formatting does not imply
that tests ran or that a suggested fix was applied. Native applyable suggestions
are not generated by this formatting pass.

The default mention is `@rush-reviewer`; `/rush` commands remain unchanged.
This changes the recognized command alias, not the GitHub App account name or
GitHub mention autocomplete. Existing local mention overrides should be set to
`RUSH_GITHUB_MENTION=rush-reviewer` before recreating the app.
