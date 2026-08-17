#!/usr/bin/env bash
# Installs the official SagerNet/sing-box static binary into ./bin so the
# health-check engine (app/quality.py) can run real per-protocol
# connectivity probes instead of a plain TCP baseline.
# Safe to re-run; it no-ops if sing-box is already on PATH.
set -uo pipefail

if command -v sing-box >/dev/null 2>&1; then
  echo "sing-box already installed: $(command -v sing-box)"
  exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SB_ARCH="amd64" ;;
  aarch64|arm64) SB_ARCH="arm64" ;;
  armv7l) SB_ARCH="armv7" ;;
  *) echo "Unsupported arch for sing-box: $ARCH — skipping install (TCP/UDP fallback will be used)"; exit 0 ;;
esac

# Ask GitHub for the latest tag; fall back to a known-good pinned version
# if the API is rate-limited or unreachable at build time.
API_BODY="$(curl -s https://api.github.com/repos/SagerNet/sing-box/releases/latest || true)"
VERSION="$(python3 - "$API_BODY" <<'PY'
import json,sys
try:
    d=json.loads(sys.argv[1])
    tag=d.get("tag_name","")
    print(tag.lstrip("v"))
except Exception:
    print("")
PY
)"
if [ -z "$VERSION" ]; then
  VERSION="1.13.5"
  echo "Could not resolve latest sing-box version from GitHub API; using pinned fallback ${VERSION}"
fi

PKG="sing-box-${VERSION}-linux-${SB_ARCH}"
URL="https://github.com/SagerNet/sing-box/releases/download/v${VERSION}/${PKG}.tar.gz"

mkdir -p bin
if ! curl -fsSL "$URL" -o "/tmp/${PKG}.tar.gz"; then
  echo "sing-box download failed (${URL}) — skipping install; TCP/UDP fallback will be used"
  exit 0
fi
tar -xzf "/tmp/${PKG}.tar.gz" -C /tmp
cp "/tmp/${PKG}/sing-box" bin/sing-box
chmod +x bin/sing-box
rm -rf "/tmp/${PKG}" "/tmp/${PKG}.tar.gz"

echo "sing-box ${VERSION} installed to ./bin/sing-box"
