#!/usr/bin/env bash
set -euo pipefail

# Recreate the venv for Linux — the host .venv is a macOS build and won't work here.
echo "[entrypoint] Syncing uv environment for Linux..."
cd /workspace
uv sync
echo "[entrypoint] uv sync complete."

# 2. Wait for manual claude login
echo "[entrypoint] waiting for 60 seconds"
sleep 60

# 3. Execute the command and log it
echo "[entrypoint] ready to run claude"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# stdbuf -oL -eL claude --verbose --dangerously-skip-permissions "$(cat /workspace/scripts/autonomous_dev.md)" 2>&1 | stdbuf -oL tee "/workspace/logs/session_${TIMESTAMP}.log"

exec "$@"
