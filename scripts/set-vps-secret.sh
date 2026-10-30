#!/usr/bin/env bash
# Kevin runs this himself: `scripts/set-vps-secret.sh ANTHROPIC_API_KEY` (or ALPACA_API_KEY, ALPACA_SECRET_KEY, ...).
# Reads the value without echoing it, writes NAME=value into /opt/stack/.env on the VPS (replacing an existing line
# for that name, keeping a dated backup), and restarts tradehub. Nothing is printed or logged.
set -euo pipefail
NAME=${1:?usage: scripts/set-vps-secret.sh NAME}
[[ $NAME =~ ^[A-Z][A-Z0-9_]{2,63}$ ]] || { echo "not a variable name: $NAME" >&2; exit 2; }
SSH=(ssh -i ~/.ssh/id_ed25519_openclaw ubuntu@40.160.91.131)

read -rsp "$NAME: " value; echo
[ -n "$value" ] || { echo "empty value, nothing written" >&2; exit 1; }
[[ $value != *$'\n'* ]] || { echo "value has a newline, nothing written" >&2; exit 1; }

printf '%s=%s\n' "$NAME" "$value" | "${SSH[@]}" "set -e; cd /opt/stack
  sudo -n cp -p .env .env.bak-$NAME-\$(date +%Y%m%d-%H%M)
  sudo -n sed -i '/^$NAME=/d' .env
  sudo -n tee -a .env >/dev/null
  sudo -n docker compose --profile tradehub up -d --no-deps tradehub >/dev/null
  echo '$NAME written; tradehub restarted'"
