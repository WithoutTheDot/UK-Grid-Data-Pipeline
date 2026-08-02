#!/usr/bin/env bash
set -euo pipefail

PROJECT=/media/goog/Projects1/UKEngergy
LOG="$PROJECT/pipeline.log"

cd "$PROJECT"

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  python3 ingest/fetch_all.py
  /home/goog/.local/bin/dbt run --quiet
  echo "--- done ---"
} >> "$LOG" 2>&1
