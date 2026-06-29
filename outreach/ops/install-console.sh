#!/usr/bin/env bash
# Install the SettlePay outreach operator console as an always-on LOCAL service.
#
# Registers a macOS LaunchAgent that runs uvicorn on 127.0.0.1:8787 with
# RunAtLoad + KeepAlive, so the dashboard is always reachable at
#   http://localhost:8787/dashboard
# across logouts and reboots.
#
# WHY a deployed copy: macOS TCC blocks launchd agents from reading
# ~/Documents (a privacy-protected folder), so we deploy a self-contained
# runtime (code + venv + .env) under ~/Library/Application Support, which is not
# protected. Re-run this script after code changes to redeploy.
#
# Bound to localhost only and intentionally NOT exposed publicly: the console
# has no authentication and holds a service-role DB connection.
#
# Uninstall with: ops/uninstall-console.sh
set -euo pipefail

LABEL="uk.settlepay.outreach.console"
PORT="${OUTREACH_CONSOLE_PORT:-8787}"

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$OPS_DIR/.." && pwd)"                       # repo's outreach/ project dir
RUNTIME="$HOME/Library/Application Support/SettlePayOutreach"
LOG_DIR="$RUNTIME/logs"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

command -v uv >/dev/null || { echo "error: 'uv' not found (needed to build the runtime venv)." >&2; exit 1; }

mkdir -p "$RUNTIME/outreach" "$LOG_DIR" "$HOME/Library/LaunchAgents"

# 1. deploy a self-contained copy OUTSIDE ~/Documents (TCC). Re-running redeploys.
rsync -a --delete --exclude='__pycache__' "$SRC_DIR/outreach/" "$RUNTIME/outreach/"
cp "$SRC_DIR/sequence_config.json" "$RUNTIME/sequence_config.json"
if [[ -f "$SRC_DIR/.env" ]]; then
  install -m 600 "$SRC_DIR/.env" "$RUNTIME/.env"
else
  echo "warn: $SRC_DIR/.env not found — the console will fail to reach the DB." >&2
fi

# 2. build the runtime venv (Python 3.12 via uv) + the web deps
[[ -x "$RUNTIME/.venv/bin/uvicorn" ]] || uv venv --python 3.12 "$RUNTIME/.venv"
uv pip install --python "$RUNTIME/.venv/bin/python" -q \
  "psycopg[binary]>=3.2" "httpx>=0.27" "python-dotenv>=1.0" \
  "fastapi>=0.110" "uvicorn>=0.29" "python-multipart>=0.0.9"

# 3. register the LaunchAgent
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNTIME/.venv/bin/uvicorn</string>
    <string>outreach.web:app</string>
    <string>--app-dir</string><string>$RUNTIME</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$RUNTIME</string>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONPATH</key><string>$RUNTIME</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG_DIR/console.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/console.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load -w "$PLIST"

echo "Deployed runtime: $RUNTIME"
echo "Installed LaunchAgent: $LABEL"
echo "Console (always-on, local): http://localhost:$PORT/dashboard"
echo "Logs: $LOG_DIR/console.log"
