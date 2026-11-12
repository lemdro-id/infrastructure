#!/bin/sh
# Writes this machine's Fly ID and the app's machine list into nginx maps,
# then runs nginx. Fly sets FLY_MACHINE_ID in every machine's environment. If
# it is missing or malformed, $lui_self is empty and the sticky-routing rules
# in nginx.conf turn themselves off (no cookie, no replay). If the machine
# list lookup fails, the list is empty and nothing is replayed until
# lui-peers.sh fills it in.
set -eu
id="${FLY_MACHINE_ID:-}"
case "$id" in
  *[!0-9a-f]*|"") id="" ;;
esac
printf 'map "" $lui_self { default "%s"; }\n' "$id" > /etc/nginx/lui-self.conf
/usr/local/bin/node /usr/local/bin/lui-peers.js /etc/nginx/lui-peers.conf || [ $? -eq 3 ] || \
  printf 'map $lui_cookie $lui_known { default ""; }\n' > /etc/nginx/lui-peers.conf
exec /usr/sbin/nginx -g "daemon off;"
