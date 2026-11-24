#!/usr/bin/env bash
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
# Renders the fixed map for every pattern and several viewpoints with the headless engine:
# exit 0, no error text, picture not one color, bit-identical on repeat. Plus the
# counter-check against the upstream renderer limits (separate build, own directory).
# Writes out/map-<pattern>.png (centre view) when POV_PNG=1.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "${ROOT}/tests/run_limited.sh"
IWAD="${POV_TEST_IWAD:-${ROOT}/assets/freedoom/freedoom1.wad}"
BIN="${ROOT}/doomgeneric/cosmergon-pov-headless"
OLD="${ROOT}/doomgeneric/cosmergon-pov-headless-upstream"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
FAILS=0
MAXMS=0
MAXMS_CASE=""

fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS + 1)); }
ok() { echo "ok: $*"; }

[ -f "${IWAD}" ] || { echo "FAIL: ${IWAD} missing (run scripts/download-freedoom.sh)" >&2; exit 1; }
make -C "${ROOT}/doomgeneric" -f Makefile.headless -j4 >"${WORK}/build.log" 2>&1 \
    || { cat "${WORK}/build.log" >&2; echo "FAIL: build" >&2; exit 1; }
make -C "${ROOT}/doomgeneric" -f Makefile.headless UPSTREAM_LIMITS=1 -j4 >"${WORK}/build-old.log" 2>&1 \
    || { cat "${WORK}/build-old.log" >&2; echo "FAIL: build with upstream limits" >&2; exit 1; }
ok "build (raised and upstream limits)"

# run <binary> <wad> <outdir> <frames> <every> ; never a window: no DISPLAY, no stdin
run() {
    mkdir -p "$3"
    run_limited 60 env -u DISPLAY -u WAYLAND_DISPLAY POV_OUT="$3" POV_EVERY="$5" POV_FRAMES="$4" \
        "$1" -iwad "${IWAD}" -file "$2" -warp 1 1 </dev/null >/dev/null 2>"$3.err"
}

# name:x,y,angle
VIEWS=("centre:24.5,24.5,0" "corner:0.5,0.5,45" "edge:0.5,24.5,90")

for pattern in flat checker full random stairs; do
    for view in "${VIEWS[@]}"; do
        vname="${view%%:*}"
        vspec="${view#*:}"
        case="${pattern}/${vname}"
        wad="${WORK}/${pattern}-${vname}.wad"
        python3 "${ROOT}/tools/make_map.py" --pattern "${pattern}" --seed 1 --start "${vspec}" -o "${wad}" >/dev/null \
            || { fail "${case}: generator"; continue; }
        run "${BIN}" "${wad}" "${WORK}/a-${pattern}-${vname}" 70 70; rc=$?
        if [ "${rc}" -ne 0 ]; then fail "${case}: exit ${rc}: $(tail -n 2 "${WORK}/a-${pattern}-${vname}.err" | tr '\n' ' ')"; continue; fi
        if grep -qi "error\|no more\|overflow" "${WORK}/a-${pattern}-${vname}.err"; then fail "${case}: error text on stderr"; continue; fi
        frame="${WORK}/a-${pattern}-${vname}/frame-000070.ppm"
        [ -f "${frame}" ] || { fail "${case}: no frame"; continue; }
        colors=$(python3 "${ROOT}/tools/ppm_stats.py" colors "${frame}")
        [ "${colors}" -gt 16 ] || fail "${case}: picture has only ${colors} colors"
        run "${BIN}" "${wad}" "${WORK}/b-${pattern}-${vname}" 70 70
        if cmp -s "${frame}" "${WORK}/b-${pattern}-${vname}/frame-000070.ppm"; then
            ok "${case}: exit 0, ${colors} colors, repeat is bit-identical"
        else
            fail "${case}: repeat differs"
        fi
        ms=$(sed -n 's/.*ms_per_frame=\([0-9.]*\).*/\1/p' "${WORK}/a-${pattern}-${vname}.err")
        echo "    ms/frame ${ms}; $(grep -o 'highwater.*' "${WORK}/a-${pattern}-${vname}.err")"
        if awk -v a="${ms}" -v b="${MAXMS}" 'BEGIN { exit !(a > b) }'; then MAXMS="${ms}"; MAXMS_CASE="${case}"; fi
        if [ "${POV_PNG:-0}" = "1" ] && [ "${vname}" = "centre" -o "${vname}" = "corner" ]; then
            mkdir -p "${ROOT}/out"
            python3 "${ROOT}/tools/ppm2png.py" "${frame}" "${ROOT}/out/map-${pattern}-${vname}.png"
        fi
    done
done
echo "slowest: ${MAXMS} ms/frame (${MAXMS_CASE})"

# The first written frame must already show the map (no title, no melt): compare frame 1 with frame 70
# above the weapon sprite (rows 0..223 of 400; the raising/bobbing weapon is the only change from row 226).
python3 "${ROOT}/tools/make_map.py" --pattern checker -o "${WORK}/first.wad" >/dev/null
run "${BIN}" "${WORK}/first.wad" "${WORK}/first" 70 1
if python3 "${ROOT}/tools/ppm_stats.py" same-view "${WORK}/first/frame-000001.ppm" "${WORK}/first/frame-000070.ppm" 224; then
    ok "first frame already shows the map (3D view equals frame 70)"
else
    fail "first frame differs from frame 70 (title, wipe or load still running)"
fi

# Counter-check: the upstream limits must fail on a map the raised limits draw.
python3 "${ROOT}/tools/make_map.py" --pattern checker --start 0.5,0.5,45 -o "${WORK}/gp.wad" >/dev/null
run "${OLD}" "${WORK}/gp.wad" "${WORK}/gp-old" 70 70; rc_old=$?
run "${BIN}" "${WORK}/gp.wad" "${WORK}/gp-new" 70 70; rc_new=$?
if [ "${rc_old}" -ne 0 ] && grep -q "no more drawsegs (256)" "${WORK}/gp-old.err" && [ "${rc_new}" -eq 0 ]; then
    ok "counter-check: upstream limits stop (exit ${rc_old}: $(grep -m1 'no more' "${WORK}/gp-old.err")), raised limits draw (exit ${rc_new})"
else
    fail "counter-check: old exit ${rc_old}, new exit ${rc_new}"
fi

if [ "${FAILS}" -ne 0 ]; then
    echo "${FAILS} check(s) failed" >&2
    exit 1
fi
echo "ALL PASSED"
