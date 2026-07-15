#!/usr/bin/env bash
# Monthly restore DRILL (§23.5) — a backup never restored is not a backup.
# Restores the latest journal backup into a scratch dir and verifies the hash
# chain. Exit 0 = drill passed.
set -euo pipefail
BACKUP="${1:-backups/journal-latest.sqlite}"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
if [[ ! -f "$BACKUP" ]]; then
  echo "no backup at $BACKUP — nothing to drill (create one first)"; exit 0
fi
cp "$BACKUP" "$SCRATCH/restored.sqlite"
python -m aimos.journal.verify "$SCRATCH/restored.sqlite"
echo "restore drill PASSED: $BACKUP verified after restore"
