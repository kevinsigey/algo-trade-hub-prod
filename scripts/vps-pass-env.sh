#!/usr/bin/env bash
# Kevin runs this himself: `scripts/vps-pass-env.sh NAME [NAME...]`. /opt/stack/compose.yml passes the tradehub
# container a fixed list of variables, so a secret in .env doesn't reach the app until its name is listed.
# Adds each missing name, keeping a dated backup, checks the file still parses (restoring the backup if not), and
# restarts tradehub. It writes names only and never reads a value. Don't run it while a deploy is in progress.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: scripts/vps-pass-env.sh NAME [NAME...]" >&2; exit 2; }
for name in "$@"; do
  [[ $name =~ ^[A-Z][A-Z0-9_]{2,63}$ ]] || { echo "not a variable name: $name" >&2; exit 2; }
done
ssh -i ~/.ssh/id_ed25519_openclaw ubuntu@40.160.91.131 bash -s -- "$@" <<'REMOTE'
set -euo pipefail
cd /opt/stack
backup="compose.yml.bak-env-$(date +%Y%m%d-%H%M%S)"
sudo -n cp -p compose.yml "$backup"
for name in "$@"; do
  sudo -n grep -q "^      $name:" compose.yml && { echo "$name already listed"; continue; }
  sudo -n awk -v name="$name" '{ print } /^      TRADEHUB_PAPER_ORDERS_BIG:/ { printf "      %s: ${%s:-}\n", name, name }' \
    compose.yml | sudo -n tee compose.yml.new >/dev/null
  sudo -n grep -q "^      $name:" compose.yml.new || { echo "could not find where to add $name" >&2; sudo -n rm -f compose.yml.new; exit 1; }
  sudo -n cp compose.yml.new compose.yml
  sudo -n rm -f compose.yml.new
  echo "$name added"
done
if ! sudo -n docker compose --profile tradehub config -q; then
  sudo -n cp -p "$backup" compose.yml
  echo "compose.yml did not parse; restored $backup, nothing restarted" >&2
  exit 1
fi
sudo -n docker compose --profile tradehub up -d --no-deps tradehub >/dev/null
echo "tradehub restarted; backup at /opt/stack/$backup"
REMOTE
