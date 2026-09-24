#!/usr/bin/env bash
set -euo pipefail

# run from wherever the repo is checked out, cron included
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$PROJECT/pipeline.log"

# cron's PATH doesn't include ~/.local/bin, where pip --user puts dbt.
# Override with DBT=/path/to/dbt if yours lives somewhere else.
DBT="${DBT:-$(command -v dbt || echo "$HOME/.local/bin/dbt")}"

cd "$PROJECT"

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  python3 ingest/fetch_all.py
  "$DBT" run --quiet
  echo "--- done ---"
} >> "$LOG" 2>&1
