#!/bin/sh
set -eu

case "${1:-}" in
    unsafe|safe|related|missing-context|bypass|valid-exception|expired-exception|conflicting-rules|wrong-field|incomplete)
        case_id=$1 ;;
    *) echo 'Usage: sh scripts/reset-example.sh CASE_ID (see customer_lookup/cases.json)' >&2
       exit 2 ;;
esac

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
fixtures="$root/tests/fixtures/customer_lookup"
example_dir=$(mktemp -d "${TMPDIR:-/tmp}/rush-example-${case_id}.XXXXXX")

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY
unset GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_COUNT=0
export GIT_AUTHOR_NAME='Lantern Cart' GIT_AUTHOR_EMAIL='team@example.invalid'
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
export GIT_AUTHOR_DATE='2026-01-15T00:00:00+00:00'
export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"

example_git() {
    git -c core.hooksPath=/dev/null -c commit.gpgsign=false -C "$example_dir" "$@"
}

git -c init.defaultBranch=example init --template= -q "$example_dir"
cp "$fixtures/base/"* "$example_dir/"
example_git add .
example_git commit -qm 'Fictional customer lookup baseline'
example_git tag fixture-base
cp "$fixtures/heads/$case_id/"* "$example_dir/"
example_git add .
example_git commit -qm "Fictional customer lookup: $case_id"
example_git tag fixture-head
printf '%s\n' "$example_dir"
