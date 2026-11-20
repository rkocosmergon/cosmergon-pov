#!/usr/bin/env bash
# Headless smoke test: build, run 350 frames, check files, determinism and failure paths.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IWAD="${POV_TEST_IWAD:-${ROOT}/assets/freedoom/freedoom1.wad}"
BIN="${ROOT}/doomgeneric/cosmergon-pov-headless"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
FAILS=0

fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS + 1)); }
ok() { echo "ok: $*"; }

make -C "${ROOT}/doomgeneric" -f Makefile.headless -j4 >"${WORK}/build.log" 2>&1 \
    || { cat "${WORK}/build.log" >&2; echo "FAIL: build" >&2; exit 1; }
ok "build"

[ -f "${IWAD}" ] || { echo "FAIL: ${IWAD} missing (run scripts/download-freedoom.sh)" >&2; exit 1; }

run() { # run <outdir>
    mkdir -p "$1"
    POV_OUT="${POV_TEST_OUT:-$1}" POV_EVERY=35 POV_FRAMES=350 "${BIN}" -iwad "${IWAD}" >/dev/null 2>"$1.err"
}

run "${WORK}/a"; rc=$?
[ "${rc}" -eq 0 ] && ok "exit 0" || fail "exit code ${rc}"

count=$(ls "${WORK}/a"/frame-*.ppm 2>/dev/null | wc -l)
[ "${count}" -eq 10 ] && ok "10 frames written" || fail "expected 10 frames, got ${count}"

# header "P6\n640 400\n255\n" is 15 bytes
expected=$((15 + 3 * 640 * 400))
for f in "${WORK}/a"/frame-*.ppm; do
    size=$(stat -c %s "${f}")
    [ "${size}" -eq "${expected}" ] || fail "${f} has ${size} bytes, expected ${expected}"
done
ok "frame sizes checked (${expected} bytes)"

last="${WORK}/a/frame-000350.ppm"
colors=$(tail -c +16 "${last}" | od -An -v -tx1 -w3 | sort -u | wc -l)
[ "${colors}" -gt 16 ] && ok "late frame has ${colors} distinct colors" || fail "late frame is nearly one color (${colors})"

# no dialog helper may be built in: the binary must not know any dialog program
if grep -aqiE "zenity|xmessage|kdialog" "${BIN}"; then fail "binary contains a dialog program name"; else ok "no dialog program in binary"; fi

# failure paths (run without any display): the program must stop with a non-zero exit and a clear message
env -u DISPLAY -u WAYLAND_DISPLAY POV_OUT=/nonexistent-dir "${BIN}" -iwad "${IWAD}" >/dev/null 2>"${WORK}/f1.err" </dev/null; rc=$?
if [ "${rc}" -ne 0 ] && grep -q "POV_OUT" "${WORK}/f1.err"; then ok "bad POV_OUT fails (exit ${rc})"; else fail "bad POV_OUT: exit ${rc}"; fi
env -u DISPLAY -u WAYLAND_DISPLAY POV_OUT="${WORK}" "${BIN}" -iwad "${WORK}/missing.wad" >/dev/null 2>"${WORK}/f2.err" </dev/null; rc=$?
if [ "${rc}" -ne 0 ] && grep -q "not found" "${WORK}/f2.err"; then ok "missing IWAD fails (exit ${rc})"; else fail "missing IWAD: exit ${rc}"; fi

run "${WORK}/b"
sum_a="$(cd "${WORK}/a" && sha256sum frame-*.ppm 2>/dev/null)"
sum_b="$(cd "${WORK}/b" && sha256sum frame-*.ppm 2>/dev/null)"
if [ -n "${sum_a}" ] && [ "${sum_a}" = "${sum_b}" ]; then
    ok "two runs are bit-identical"
else
    fail "two runs differ"
fi

if [ "${FAILS}" -ne 0 ]; then
    echo "${FAILS} check(s) failed" >&2
    exit 1
fi
echo "ALL PASSED"
