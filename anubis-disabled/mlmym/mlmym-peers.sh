#!/bin/sh
# Writes an nginx map of this app's machine IDs (from Fly's internal DNS
# TXT record vms.<app>.internal) so nginx only fly-replays to machines that
# exist. Fly answers fly-replay to an unknown instance with HTTP 400, so a
# stale mlmym_machine cookie must never be replayed.
# usage: mlmym-peers.sh <outfile>
# exit 0 = file written (changed), 3 = unchanged, 1 = lookup failed (file untouched)
# Shell port of lemmy-ui/lui-peers.js — the mlmym image has no Node.
set -eu
out="${1:?}"
app="${FLY_APP_NAME:-}"
self="${FLY_MACHINE_ID:-}"
case "$app" in
  *[!a-z0-9-]*|'') echo "mlmym-peers: no FLY_APP_NAME" >&2; exit 1 ;;
esac

txt="$(dig +short +time=2 +tries=2 TXT "vms.${app}.internal" | tr -d '"' | tr '\n' ',')" || exit 1

ids=""
old_ifs=$IFS
IFS=','
# While IFS is comma, "set -- $entry" will not split "id region" on spaces,
# and "id region" fails the hex check. Take the first word instead.
for entry in $txt; do
  id="${entry%% *}"
  case "$id" in
    *[!0-9a-f]*|'') ;;
    *) ids="$ids $id" ;;
  esac
done
IFS=$old_ifs
case "$self" in
  *[!0-9a-f]*|'') ;;
  *) ids="$ids $self" ;;
esac

ids="$(printf '%s\n' $ids | sort -u | tr '\n' ' ')"

body="map \$mlmym_cookie \$mlmym_known {
    default \"\";
"
for id in $ids; do
  [ -n "$id" ] || continue
  body="${body}    \"$id\" \"$id\";
"
done
body="${body}}
"

if [ -f "$out" ] && [ "$(cat "$out")" = "$body" ]; then
  exit 3
fi
printf '%s' "$body" > "$out.tmp"
mv "$out.tmp" "$out"
exit 0
