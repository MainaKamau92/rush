#!/bin/sh
set -eu
hooks_path=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_path"
if [ -e "$hooks_path/pre-commit" ]; then
  echo 'Existing pre-commit hook found; review it before installing rush hooks.' >&2
  exit 1
fi
cat > "$hooks_path/pre-commit" <<'HOOK'
#!/bin/sh
set -eu
docker compose run --rm -T dev pre-commit run --all-files
HOOK
chmod +x "$hooks_path/pre-commit"
echo 'Installed Docker-based pre-commit hook.'
