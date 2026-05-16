#!/usr/bin/env bash
set -euo pipefail

# Recreate the venv for Linux — the host .venv is a macOS build and won't work here.
echo "[entrypoint] Syncing uv environment for Linux..."
cd /workspace
uv sync
echo "[entrypoint] uv sync complete."

exec "$@"
