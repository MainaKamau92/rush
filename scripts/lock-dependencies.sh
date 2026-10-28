#!/bin/sh
# Refresh the lock and its installable exports entirely inside Docker.
set -eu
uv_image=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946
run_uv() {
  docker run --rm -v "$PWD:/workspace" -w /workspace --entrypoint /uv "$uv_image" "$@"
}
run_uv lock
run_uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements/runtime.txt
run_uv export --frozen --all-groups --no-emit-project --format requirements-txt -o requirements/development.txt
run_uv export --frozen --only-group build --format requirements-txt -o requirements/build.txt
