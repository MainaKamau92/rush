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

GitHub cannot reach `127.0.0.1`, so use a forwarding channel. The simplest is
[smee.io](https://smee.io):

1. Open smee.io and choose **Start a new channel**.
2. Use the channel URL as the app's webhook URL.
3. Run the client while you test:

```sh
npx smee-client --url https://smee.io/YOUR_CHANNEL --target http://127.0.0.1:8088/github/webhook
```

The client forwards only to the webhook path. Avoid tunnels that publish the
whole service: they would also expose `/jobs`, which lists repository names,
PR numbers and commenters.

Anyone who knows a smee URL can read the events sent through it, so use a fresh
channel for the demo and don't share it. rush verifies every event's signature,
so forged events are rejected. A copied event resent under a new delivery ID is
recognized by its signed content and ignored.

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

`META_AI_KEY` is required as well. ClickUp settings are optional: when
`RUSH_CLICKUP_WORKSPACE_ID` and `CLICK_UP_API_TOKEN` are set, ticket links in
the PR description are read live, as with `rush review --pr-description`.

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
| A PR comment starting with `/rush review` | A rerun job. Before reviewing, the worker checks the commenter's **current** repository permission; without write, maintain or admin access, the job is skipped and says why. |
| Any event from a bot, including rush itself | Ignored, so rush can't trigger itself. |
| A repeated delivery ID, or the same signed event resent | Acknowledged and ignored. |
| App installation events | Acknowledged and ignored. |
| An unsigned or wrongly signed event | Rejected with 401 before anything is read or stored. |
| An event type other than PR and comment events (except `ping`) | Rejected with 422. |
| An event from a repository not listed | Rejected with 403. |

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
| Findings GitHub can't place on a line | Written in full in the summary, with the exact file, line and version. |
| Earlier findings no longer reported | Marked **Resolved** only after a *complete* review rechecked them. After an incomplete review they stay open, and the summary says how many were not rechecked. |
| The advisory check `rush review` on the head commit | Created once per commit, then updated. |

Comments are edited, never deleted, so replies in their threads are kept. rush
only edits comments written by its own app account. Model-written text is
neutralized before posting: HTML is escaped, `@` mentions don't notify anyone,
and image links don't load. The summary is capped below GitHub's size limit.
A finding no longer reported may have been fixed, waived by an approved
exception, or withdrawn; the note says so.

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

Reply in a finding's review thread with one of these commands on the first
line. Only people with write, maintain or admin access can use them; rush
checks the commenter's current permission each time.

| Command | What happens |
|---|---|
| `/rush explain [simpler\|technical\|example\|evidence\|change] [complexity=plain\|technical] [verbosity=short\|detailed] [question]` | The Meta model rewords the finding with the requested focus. |
| `/rush accept [reason]` | The acceptance is recorded with the actor. |
| `/rush dismiss <reason>` | The dismissal is recorded with the actor and reason. |
| `/rush challenge <reason>` | rush reassesses the finding from its recorded evidence. |

**Explanations**
- Complexity and verbosity are separate settings. The team defaults are
  `RUSH_EXPLAIN_COMPLEXITY` (`plain` or `technical`) and
  `RUSH_EXPLAIN_VERBOSITY` (`short` or `detailed`). A request can override
  either one; `simpler` and `technical` also set the complexity unless it is
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
