#!/bin/sh
# Refreshes /etc/nginx/mlmym-peers.conf every 30s and reloads nginx when the
# machine list changes. start-nginx.sh writes the first copy.
while :; do
  sleep 30
  if /usr/local/bin/mlmym-peers.sh /etc/nginx/mlmym-peers.conf; then
    echo "mlmym-peers: machine list changed: $(grep -o '"[0-9a-f]*" ' /etc/nginx/mlmym-peers.conf | tr -d '" ' | tr '\n' ' ')"
    /usr/sbin/nginx -t -q && /usr/sbin/nginx -s reload
  fi
done
