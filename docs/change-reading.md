# Reading a code change

`rush change-read` loads the exact committed change between two versions of a
local Git repository. It prints JSON with every changed file, its hunks, and
old/new line numbers, so later review steps can place a finding on the right
version and line. It needs no running web service, database, credentials or
model.

## Run the fictional examples

```sh
docker compose run --rm -T dev sh -ec '
  example=$(sh scripts/reset-example.sh unsafe)
  rush change-read --repository "$example" --target fixture-base --head fixture-head
'
```

Any case ID from [the examples](../tests/fixtures/customer_lookup/README.md)
works. The example repository exists only inside that container invocation.

## Choosing what to compare

Pass `--head` and exactly one of:

| Option | Compares | Output `comparison` |
|---|---|---|
| `--target BRANCH` | Head against its shared starting point (merge base) with the PR target. Changes made only on the target branch are excluded. | `merge_base` |
| `--base VERSION` | Head directly against that exact version. Anything that differs between the two is included. | `exact` |

Use `--target` for pull requests. Versions are branch names, tags or commit IDs;
ranges (`a..b`), path syntax (`main:file`) and values starting with `-` are
rejected before Git runs. Every version is resolved to a full commit ID, and the
output records `target_sha` (merge-base comparisons only), `base_sha` (the side
actually compared) and `head_sha`.

## Output

Each `files` entry has `status` (`added`, `deleted`, `modified` or `renamed`),
`old_path`/`new_path`, object IDs, file modes, rename `similarity`, counts and
`hunks`. Each hunk has a stable `id` and its old/new ranges. Each line is
`context`, `added` or `removed`, with `old_line` and/or `new_line`:

- Removed lines and deleted files keep their old-side line numbers (`LEFT`).
- Renamed files keep both paths; old-side anchors use `old_path`.
- Lines are split on `\n` only, matching Git. A carriage return stays in `text`.

`scope_sha256` fingerprints the JSON scope so a review record can pin it.

## Content that is not read

Anything rush cannot read safely appears in `omissions` with a reason, and is
never listed in `files`. A scope with any omission has `status: "partial"`.
Each omission converts to a completeness-affecting `scope_excluded` limitation
for the review record.

| Reason | When |
|---|---|
| `invalid_path` | Not valid UTF-8, contains control characters, or has an empty, `.`, `..` or `.git` component. The path is shown escaped. |
| `symlink` | Symbolic link; the target is not followed or read. |
| `submodule` | Submodule commit change; its contents are not fetched or read. |
| `unsupported_entry` | Any other entry type or change kind. |
| `binary` | Content contains a NUL byte. |
| `not_utf8` | Content is not valid UTF-8. |
| `too_large` | A version exceeds 1 MiB. |
| `missing_object` | Content is unavailable, for example in a partial clone. |

Unknown versions, a target with no shared starting point, a path that is not a
Git repository (parent directories are not searched), and an unreadable Git
response fail with exit code 1 and a short message. Nothing partial is printed.

## What reading never does

rush reads committed Git objects only, through `--git-dir`. It does not check
out, write to the index or working tree, or read uncommitted or untracked files.
It never runs the repository's code, tests, dependency installers or setup
instructions.

Git commands run without a shell, with a minimal environment, and with system
and global Git configuration ignored. Each call disables hooks, fsmonitor,
pagers, external diff programs, text conversion, lazy fetching, network
protocols and replacement objects. Files are compared as two content objects,
so repository attributes cannot select a diff driver or filter. Repository-local
config is still read by Git, so diff output settings are fixed explicitly.
Tests confirm that helpers configured in a repository are not run.

Git must be installed. The dev image includes it; the runtime image does not
yet, so run `change-read` through the dev service. A repository owned by another
user is refused by Git's ownership check.

## Limits

This command reads the change only. [Bounded investigation](investigation.md)
provides the TCR-007 service workflow and configurable review budgets; they are
not applied by this raw inspection command. Model review belongs to TCR-008.
Copy detection is off, so copies appear as added files.
