#!/usr/bin/env bash
# Run on Pi (as toast) to install Tether prerequisites.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[tether] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git curl ufw

echo "[tether] Setting up Python virtualenv..."
python3 -m venv "$REPO_DIR/.venv"
source "$REPO_DIR/.venv/bin/activate"
pip install --quiet -e "$REPO_DIR"

echo "[tether] Checking Claude Code..."
if ! command -v claude &>/dev/null; then
  echo "[tether] ERROR: Claude Code not installed."
  echo "         Install Node 20: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
  echo "         Then: sudo npm install -g @anthropic-ai/claude-code && claude login"
  exit 1
fi
echo "[tether] Claude Code found: $(claude --version)"

echo "[tether] Creating ~/.tether-config/ if needed..."
mkdir -p ~/.tether-config

echo "[tether] Configuring UFW firewall..."
sudo ufw allow 22/tcp comment "SSH"
sudo ufw allow 8000/tcp comment "Tether dashboard (local)"
sudo ufw --force enable

echo ""
echo "[tether] Setup complete. Next steps:"
echo "  1. cp $REPO_DIR/config/config.example.yaml ~/.tether-config/config.yaml"
echo "  2. cp $REPO_DIR/config/anchors.example.yaml ~/.tether-config/anchors.yaml"
echo "  3. cp $REPO_DIR/config/plan.example.yaml ~/.tether-config/plan.yaml"
echo "  4. Edit ~/.tether-config/config.yaml with your Telegram token + chat ID"
echo "  5. nano ~/.tether-config/context.md — add your project context"
echo "  6. crontab -e — add anchor trigger entries"
