#!/bin/sh
# Refresh the lock and its installable exports entirely inside Docker.
set -eu
docker compose build lock
run_uv() {
  docker compose run --rm -T lock uv "$@"
}
run_uv lock
run_uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements/runtime.txt
run_uv export --frozen --all-groups --no-emit-project --format requirements-txt -o requirements/development.txt
run_uv export --frozen --only-group build --format requirements-txt -o requirements/build.txt
