#!/usr/bin/env bash
# setup.sh — one-shot installer for the manuscript verification toolkit.
#
# Creates ~/claude/paper-tools/.venv (or wherever this repo lives), installs
# Python dependencies, downloads Chromium for the Playwright fallback, and
# prints the next steps.
#
# Run from the repo root:
#
#   bash setup.sh
#
# Idempotent — re-running is safe.

set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"

echo "=== papers-toolkit setup ==="
echo "repo: $REPO"
echo

# 1. Python 3.10+ check.
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    echo "  macOS:    brew install python"
    echo "  Linux:    sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "[1/4] Found python3 $PY_VERSION"

# 2. Virtualenv.
VENV="$REPO/.venv"
if [ ! -d "$VENV" ]; then
    echo "[2/4] Creating venv at $VENV"
    python3 -m venv "$VENV"
else
    echo "[2/4] venv exists at $VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"
python -m pip install --upgrade --quiet pip

# 3. Dependencies.
echo "[3/4] Installing dependencies from requirements.txt"
pip install --quiet -r requirements.txt

# 4. Playwright Chromium (one-time download, ~150 MB).
echo "[4/4] Installing Playwright Chromium (for Cloudflare-blocked publisher pages)"
python -m playwright install chromium >/dev/null

echo
echo "=== setup complete ==="
echo
echo "Next steps:"
echo
echo "  1. Configure API keys.  Run:"
echo "       python3 setup_keys.py"
echo
echo "  2. Try the citation checker on the demo manuscript:"
echo "       source .venv/bin/activate"
echo "       python3 check-citations/check_citations.py examples/tiny_paper.tex"
echo
echo "  3. (Optional) wire the MCP server into Claude Desktop — see README §MCP."
echo
