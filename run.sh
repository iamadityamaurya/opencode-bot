#!/usr/bin/env bash
# Run the OpenCode Telegram bot in the foreground.
# Usage: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m opencode_telegram.main
