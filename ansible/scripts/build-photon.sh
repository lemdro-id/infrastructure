#!/usr/bin/env bash
# Build the Photon static site that box nginx serves for bare lemdro.id (/srv/photon).
# Same recipe as the 2026-11-19 build (Photon v2.4.3 @ 6609371, bun 1.4.4, ADAPTER=static, 476 files, ~7.1 MB).
# Output is functionally identical but not byte-identical: the build timestamp (_app/version.json) changes
# some chunk hashes. Verified 2026-11-19: same 476 files, same env.js, about 270 of 475 files get new chunk hashes.
# Needs Docker and git on the build machine (not the server). Usage: scripts/build-photon.sh [out-dir]
set -euo pipefail
PHOTON_TAG="${PHOTON_TAG:-v2.4.3}"
PHOTON_COMMIT="${PHOTON_COMMIT:-6609371}"
BUN_IMAGE="${BUN_IMAGE:-oven/bun:1.4.4}"
OUT="$(cd "${1:-.}" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --quiet --depth 1 --branch "$PHOTON_TAG" https://github.com/Xyphyn/photon "$WORK/photon"
got="$(git -C "$WORK/photon" rev-parse --short=7 HEAD)"
[ "$got" = "$PHOTON_COMMIT" ] || { echo "tag $PHOTON_TAG is $got, expected $PHOTON_COMMIT" >&2; exit 1; }

# Apply the Explore TopWeek default. source-patch.sh refuses to run if upstream no longer has TopDay.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_PATCH="$SCRIPT_DIR/../roles/lemdroid_patches/photon/source-patch.sh"
(cd "$WORK/photon" && "$SOURCE_PATCH")

docker run --rm -v "$WORK/photon:/app" -w /app \
  -e ADAPTER=static \
  -e PUBLIC_INSTANCE_URL=lemdro.id \
  -e PUBLIC_SSR_ENABLED=false \
  -e PUBLIC_RANDOM_PLACEHOLDERS=false \
  -e PUBLIC_MIGRATE_COOKIE=true \
  -e PUBLIC_DOCK_PANEL=true \
  -e PUBLIC_DOCK_TOP=true \
  "$BUN_IMAGE" sh -c 'bun install --frozen-lockfile && bun run build'

grep -q 'PUBLIC_INSTANCE_URL:"lemdro.id"' "$WORK/photon/build/_app/env.js"
tar -C "$WORK/photon/build" -czf "$OUT/photon-$PHOTON_TAG.tar.gz" .
echo "$OUT/photon-$PHOTON_TAG.tar.gz ($(find "$WORK/photon/build" -type f | wc -l) files)"
