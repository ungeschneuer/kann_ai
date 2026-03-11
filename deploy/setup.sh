#!/usr/bin/env bash
# First-time setup on Uberspace.
# Run from the repo root on the server:
#   bash deploy/setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER="$(whoami)"
VENV_PYTHON="$REPO_DIR/.venv/bin/python"
SUPERVISORD_CONF_DIR="$HOME/.config/supervisord/conf.d"
LOG_DIR="/var/www/virtual/$USER/logs"

echo "=== kann_ai_bot setup for user: $USER ==="
echo "Repo: $REPO_DIR"

# ---- 1. Install uv if missing ----
if ! command -v uv &>/dev/null; then
    echo "--- Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# ---- 2. Install Python deps ----
echo "--- Installing Python dependencies..."
cd "$REPO_DIR"
uv sync --no-dev

# ---- 3. Log directory ----
mkdir -p "$LOG_DIR"

# ---- 4. Collect required config ----
echo ""
echo "=== Configuration ==="

read -rp "Uberspace username [$USER]: " INPUT_USER
UBERSPACE_USER="${INPUT_USER:-$USER}"

read -rp "Port for DE instance (get one with: uberspace web backend list): " PORT_DE
read -rp "Port for EN instance: " PORT_EN

read -rp "Domain for DE instance (e.g. kann-ki.schneuer.online): " DOMAIN_DE
read -rp "Domain for EN instance (e.g. can-ai.schneuer.online): " DOMAIN_EN

# ---- 5. Create .env files if missing ----
for LOCALE in de en; do
    ENV_FILE="$REPO_DIR/.env.$LOCALE"
    EXAMPLE_FILE="$REPO_DIR/.env.$LOCALE.example"
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$EXAMPLE_FILE" ]]; then
            cp "$EXAMPLE_FILE" "$ENV_FILE"
            echo "--- Created $ENV_FILE from example. Edit it with your credentials before starting bots."
        else
            echo "WARNING: $ENV_FILE missing and no example found. Create it manually."
        fi
    else
        echo "--- $ENV_FILE already exists, skipping."
    fi
done

# ---- 6. Add domains first (backends must be scoped to known domains) ----
echo ""
echo "--- Adding domains..."
uberspace web domain add "$DOMAIN_DE" 2>/dev/null || echo "  $DOMAIN_DE already added or DNS not ready."
uberspace web domain add "$DOMAIN_EN" 2>/dev/null || echo "  $DOMAIN_EN already added or DNS not ready."

# ---- 7. Register domain-specific web backends ----
echo "--- Registering web backends..."
uberspace web backend set "$DOMAIN_DE" --http --port "$PORT_DE" 2>/dev/null || true
echo "DE backend registered on port $PORT_DE for $DOMAIN_DE"
uberspace web backend set "$DOMAIN_EN" --http --port "$PORT_EN" 2>/dev/null || true
echo "EN backend registered on port $PORT_EN for $DOMAIN_EN"

# ---- 8. Install supervisord configs ----
echo "--- Installing supervisord configs..."
mkdir -p "$SUPERVISORD_CONF_DIR"

for PROG in web_de bot_de web_en bot_en; do
    SRC="$REPO_DIR/supervisord/${PROG}.ini"
    DST="$SUPERVISORD_CONF_DIR/kann_ai_${PROG}.ini"
    # Replace placeholder ports with actual values
    sed \
        -e "s/PORT_DE/$PORT_DE/g" \
        -e "s/PORT_EN/$PORT_EN/g" \
        "$SRC" > "$DST"
    echo "  Installed $DST"
done

# ---- 9. Start processes ----
echo "--- Starting processes..."
supervisorctl reread
supervisorctl update
supervisorctl start kann_ai_web_de kann_ai_bot_de kann_ai_web_en kann_ai_bot_en

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $REPO_DIR/.env.de and $REPO_DIR/.env.en with real credentials"
echo "  2. Run: supervisorctl restart kann_ai_bot_de kann_ai_bot_en"
echo "  3. Check logs:  tail -f $LOG_DIR/kann_ai_web_de.log"
echo "  4. Check status: supervisorctl status"
echo ""
echo "Domains:"
echo "  DE: https://$DOMAIN_DE"
echo "  EN: https://$DOMAIN_EN"
