#!/usr/bin/env bash
set -euo pipefail

# Export a clean, git-ready copy of the project to a target directory.
# Usage: tools/export_release.sh [DEST_DIR]
# Example: tools/export_release.sh ../office-nfl-pickems-release

SRC_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
DEST_DIR="${1:-"$SRC_DIR/../office-nfl-pickems-release"}"

mkdir -p "$DEST_DIR"

# Rsync project excluding local/dev artifacts, venv, node_modules, DB files, logs
rsync -av --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'logs/' \
  --exclude '.DS_Store' \
  --exclude '.cookies.txt' \
  --exclude '.pickems_cookies.txt' \
  --exclude '.session_cookies.txt' \
  --exclude 'dash.html' \
  --exclude 'dev_games.html' \
  --exclude 'data/*.db' \
  --exclude 'data/*.sqlite' \
  --exclude 'data/backups/*' \
  --exclude 'data/avatars/*' \
  "$SRC_DIR"/ "$DEST_DIR"/

# Post-clean destination in case prior exports left excluded files behind
rm -f "$DEST_DIR/.env" || true
rm -rf "$DEST_DIR/node_modules" "$DEST_DIR/logs" || true
rm -f "$DEST_DIR/dash.html" "$DEST_DIR/dev_games.html" || true
rm -f "$DEST_DIR"/data/*.db "$DEST_DIR"/data/*.sqlite 2>/dev/null || true
rm -rf "$DEST_DIR"/data/backups/* "$DEST_DIR"/data/avatars/* 2>/dev/null || true

# Ensure empty data subdirectories (gitkept) exist
mkdir -p "$DEST_DIR/data/avatars" "$DEST_DIR/data/backups"
# Preserve gitkeep files if present
if [[ ! -f "$DEST_DIR/data/.gitkeep" ]]; then
  echo > "$DEST_DIR/data/.gitkeep"
fi
if [[ ! -f "$DEST_DIR/data/avatars/.gitkeep" ]]; then
  mkdir -p "$DEST_DIR/data/avatars"
  echo > "$DEST_DIR/data/avatars/.gitkeep"
fi
if [[ ! -f "$DEST_DIR/data/backups/.gitkeep" ]]; then
  mkdir -p "$DEST_DIR/data/backups"
  echo > "$DEST_DIR/data/backups/.gitkeep"
fi

cat <<EOF
Export complete -> $DEST_DIR
Next steps:
  cd "$DEST_DIR"
  git init && git add . && git commit -m "Initial release copy"
  # Create a GitHub repo and push:
  # git remote add origin git@github.com:<you>/office-nfl-pickems.git
  # git push -u origin main

Docker quick start:
  cp .env.example .env
  # Optionally change HOST_PORT (defaults to 8000)
  docker compose up --build -d
  # App at: http://localhost:\${HOST_PORT:-8000}
EOF
