#!/usr/bin/env bash
# Rolling update on Uberspace. Run from repo root on the server:
#   bash deploy/update.sh [--restart-bots]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESTART_BOTS=false

for arg in "$@"; do
    case "$arg" in
        --restart-bots) RESTART_BOTS=true ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

cd "$REPO_DIR"

echo "=== kann_ai_bot update ==="

# ---- 1. Pull latest code ----
echo "--- git pull..."
git pull --ff-only

# ---- 2. Sync dependencies ----
echo "--- uv sync..."
uv sync --no-dev

# ---- 3. Reload supervisord config (pick up any .ini changes) ----
echo "--- supervisorctl reread + update..."
supervisorctl reread
supervisorctl update

# ---- 4. Restart web instances (graceful: one at a time) ----
echo "--- Restarting web instances..."
supervisorctl restart kann_ai_web_de
sleep 3
supervisorctl restart kann_ai_web_en
sleep 3

# ---- 5. Optionally restart bots ----
if $RESTART_BOTS; then
    echo "--- Restarting bots..."
    supervisorctl restart kann_ai_bot_de
    supervisorctl restart kann_ai_bot_en
fi

# ---- 6. Status ----
echo ""
echo "=== Status ==="
supervisorctl status kann_ai_web_de kann_ai_bot_de kann_ai_web_en kann_ai_bot_en
