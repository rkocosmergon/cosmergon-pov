#!/usr/bin/env bash
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
# Builds SDL2 as a static library from a pinned source archive (SHA-256 checked, abort on a mismatch).
#   scripts/build-sdl2-static.sh <prefix> [<work-dir>]
# Result: <prefix>/bin/sdl2-config (use: make -f Makefile.pov SDL2_CONFIG=<prefix>/bin/sdl2-config SDL2_STATIC=1),
# <prefix>/LICENSE-SDL2.txt. Only video is built (the program calls SDL_Init(SDL_INIT_VIDEO) and plays no sound).
# Environment passed through to configure: CC, CFLAGS, LDFLAGS, MACOSX_DEPLOYMENT_TARGET.
# SDL2_CONFIGURE_EXTRA: more configure options (for example --host=... when cross compiling).
# Needs: curl, tar, make, a C compiler; on Linux the X11/Wayland development headers (the window system
# libraries themselves are loaded at run time by SDL, they are not linked).
set -euo pipefail

VERSION="2.32.10"
URL="https://github.com/libsdl-org/SDL/releases/download/release-${VERSION}/SDL2-${VERSION}.tar.gz"
SHA256="5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165"

[ $# -ge 1 ] || { echo "usage: $0 <prefix> [<work-dir>]" >&2; exit 2; }
mkdir -p "$1"
PREFIX="$(cd "$1" && pwd)"
WORK="${2:-$(mktemp -d)}"
mkdir -p "${WORK}"
WORK="$(cd "${WORK}" && pwd)"

if command -v sha256sum >/dev/null 2>&1; then
    sha() { sha256sum "$1" | cut -d' ' -f1; }
else
    sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
fi

ARCHIVE="${WORK}/SDL2-${VERSION}.tar.gz"
curl -fsSL -o "${ARCHIVE}" "${URL}"
ACTUAL="$(sha "${ARCHIVE}")"
if [ "${ACTUAL}" != "${SHA256}" ]; then
    echo "build-sdl2-static: SHA-256 mismatch for ${URL}" >&2
    echo "  expected ${SHA256}" >&2
    echo "  actual   ${ACTUAL}" >&2
    exit 1
fi

tar -xzf "${ARCHIVE}" -C "${WORK}"
SRC="${WORK}/SDL2-${VERSION}"
mkdir -p "${WORK}/build"
cd "${WORK}/build"
# shellcheck disable=SC2086
"${SRC}/configure" --prefix="${PREFIX}" --disable-shared --enable-static \
    --disable-audio --disable-joystick --disable-haptic --disable-hidapi --disable-sensor \
    --disable-dbus --disable-ibus --disable-fcitx --disable-video-kmsdrm --disable-video-vulkan \
    ${SDL2_CONFIGURE_EXTRA:-}
make -j4
make install
cp "${SRC}/LICENSE.txt" "${PREFIX}/LICENSE-SDL2.txt"
echo "build-sdl2-static: SDL ${VERSION} in ${PREFIX}"
"${PREFIX}/bin/sdl2-config" --version --static-libs
