#!/usr/bin/env bash
# Stop and remove the always-on outreach console LaunchAgent.
set -euo pipefail
LABEL="uk.settlepay.outreach.console"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNTIME="$HOME/Library/Application Support/SettlePayOutreach"
launchctl unload "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"
echo "Removed LaunchAgent: $LABEL (console stopped)."
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$RUNTIME"
  echo "Purged runtime: $RUNTIME"
else
  echo "Deployed runtime left in place ($RUNTIME). Re-run with --purge to remove it."
fi
