#!/usr/bin/env bash
# Kevin runs this himself: reads the Alpaca paper keys without echoing them, writes them into
# /opt/stack/.env on the VPS, and restarts tradehub. Nothing is printed or logged.
set -euo pipefail
SSH=(ssh -i ~/.ssh/id_ed25519_openclaw ubuntu@40.160.91.131)

if "${SSH[@]}" 'sudo -n grep -q "^ALPACA_API_KEY=" /opt/stack/.env'; then
  echo "ALPACA_API_KEY is already in /opt/stack/.env. Remove those two lines first if you are replacing them." >&2
  exit 1
fi
read -rsp "Alpaca PAPER API key ID: " k; echo
read -rsp "Alpaca PAPER secret key: " s; echo
[ -n "$k" ] && [ -n "$s" ] || { echo "empty key, nothing written" >&2; exit 1; }
printf 'ALPACA_API_KEY=%s\nALPACA_SECRET_KEY=%s\n' "$k" "$s" \
  | "${SSH[@]}" 'sudo -n tee -a /opt/stack/.env >/dev/null && cd /opt/stack && sudo -n docker compose --profile tradehub up -d --no-deps tradehub >/dev/null && echo "written; tradehub restarted"'
