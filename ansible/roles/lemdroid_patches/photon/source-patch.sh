#!/bin/sh
# Run from the root of a Photon checkout (tested against v2.4.3 layout) before building.
set -eu
f=src/routes/explore/+layout.ts
grep -q "TopDay" "$f" || { echo "TopDay not found in $f: upstream changed, review by hand" >&2; exit 1; }
sed -i 's/TopDay/TopWeek/g' "$f"
grep -n "TopWeek" "$f"
