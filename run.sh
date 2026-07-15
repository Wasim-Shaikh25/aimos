#!/usr/bin/env bash
# AIMOS — one command: install backend + build frontend + serve both on one port.
#
#   ./run.sh              # offline synthetic data (no keys/network), full stack
#   ./run.sh --live       # live PUBLIC candles (needs internet; still no API keys)
#
# Then open http://localhost:8000  (API + dashboard on the same port).
# Optional: cp .env.example .env  and set TELEGRAM_BOT_TOKEN for alerts.
set -euo pipefail
cd "$(dirname "$0")"

LIVE="false"
[[ "${1:-}" == "--live" ]] && LIVE="true"

echo "==> [1/3] Python backend"
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e '.[serve]'
[[ "$LIVE" == "true" ]] && pip install -q -e '.[data]'   # ccxt for live public candles

echo "==> [2/3] Frontend build"
if command -v npm >/dev/null 2>&1; then
  ( cd dashboard && npm install --no-audit --no-fund --silent && npm run build )
  echo "    dashboard built -> dashboard/dist"
else
  echo "    npm not found — serving API only (install Node to build the UI)"
fi

echo "==> [3/3] Serve  (http://localhost:${AIMOS_PORT:-8000})"
export AIMOS__FEATURES__LIVE_DATA="$LIVE"
# load .env if present (Telegram token etc.)
[[ -f .env ]] && { set -a; source .env; set +a; }
exec python -m aimos.runtime.serve
