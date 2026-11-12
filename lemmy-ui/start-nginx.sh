#!/bin/sh
# Writes this machine's Fly ID into an nginx map, then runs nginx.
# Fly sets FLY_MACHINE_ID in every machine's environment. If it is missing or
# malformed, $lui_self is empty and the sticky-routing rules in nginx.conf
# turn themselves off (no cookie, no replay).
set -eu
id="${FLY_MACHINE_ID:-}"
case "$id" in
  *[!0-9a-f]*|"") id="" ;;
esac
printf 'map "" $lui_self { default "%s"; }\n' "$id" > /etc/nginx/lui-self.conf
exec /usr/sbin/nginx -g "daemon off;"
