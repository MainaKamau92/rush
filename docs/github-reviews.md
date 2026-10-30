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

The service never checks out or runs PR code. Publishing the result on the PR
arrives with TCR-017–019. Until then, results are stored in the review record,
and job progress is shown at `/jobs`.

## Create the GitHub App

Create the app under the account or organization that owns the demo repository:
**Settings → Developer settings → GitHub Apps → New GitHub App**.

| Setting | Value |
|---|---|
| Webhook URL | Your forwarding URL (see below) |
| Webhook secret | A long random value, e.g. from `openssl rand -hex 32`; put it in `.env` |
| Repository permissions | Metadata: read-only, Contents: read-only, Issues: read-only, Pull requests: read and write, Checks: read and write |
| Subscribe to events | Pull request, Issue comment |
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
