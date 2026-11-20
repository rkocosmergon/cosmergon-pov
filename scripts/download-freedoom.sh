#!/usr/bin/env bash
# Download Freedoom (pinned version), verify SHA-256, extract freedoom1.wad and COPYING.txt.
set -euo pipefail

VERSION="0.13.0"
URL="https://github.com/freedoom/freedoom/releases/download/v${VERSION}/freedoom-${VERSION}.zip"
SHA256="3f9b264f3e3ce503b4fb7f6bdcb1f419d93c7b546f4df3e874dd878db9688f59"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/assets/freedoom"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

mkdir -p "${DEST}"
curl -fsSL -o "${WORK}/freedoom.zip" "${URL}"

ACTUAL="$(sha256sum "${WORK}/freedoom.zip" | cut -d' ' -f1)"
if [ "${ACTUAL}" != "${SHA256}" ]; then
    echo "download-freedoom: SHA-256 mismatch" >&2
    echo "  expected ${SHA256}" >&2
    echo "  actual   ${ACTUAL}" >&2
    exit 1
fi

python3 -I - "${WORK}/freedoom.zip" "${DEST}" "${VERSION}" <<'PY'
import sys, zipfile
archive, dest, version = sys.argv[1:4]
with zipfile.ZipFile(archive) as z:
    for name in ("freedoom1.wad", "COPYING.txt"):
        data = z.read(f"freedoom-{version}/{name}")
        with open(f"{dest}/{name}", "wb") as f:
            f.write(data)
PY
echo "download-freedoom: ok, freedoom ${VERSION} in ${DEST}"
