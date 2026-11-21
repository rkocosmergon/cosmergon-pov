#!/usr/bin/env bash
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
# Short probes on the device: one run of <seconds> per setting, CPU of the POV
# program and of the compositor from /proc, plus the program's own measures.
#   bash tools/probe_device.sh <seconds> <out-file> "<env settings>" ["<env settings>" ...]
# e.g. bash tools/probe_device.sh 60 out.txt "POV_FPS=35" "POV_FPS=20" "POV_FPS=35 POV_SOFTWARE=1"
set -u
SECS="${1:?seconds}"; OUT="${2:?out file}"; shift 2
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
TCK="$(getconf CLK_TCK)"
COMP="$(pgrep -x Hyprland | head -1)"
cpu() { sed 's/^.*) //' "/proc/$1/stat" | awk '{print $12 + $13}'; }
FIFO="$XDG_RUNTIME_DIR/cosmergon-pov-probe.fifo"
[ -p "$FIFO" ] || mkfifo -m 600 "$FIFO"
: > "$OUT"
for SETTING in "$@"; do
    # shellcheck disable=SC2086
    env $SETTING "$HERE/doomgeneric/cosmergon-pov" -pov-control < "$FIFO" > /dev/null 2> "$OUT.err" &
    POV=$!
    # shellcheck disable=SC2086
    env $SETTING python3 "$HERE/tools/pov_walk.py" "$SECS" > "$FIFO" &
    WRITER=$!
    sleep 1
    a_pov="$(cpu "$POV")"; a_comp="$(cpu "$COMP")"
    T=$((SECS - 3)); sleep "$T"
    b_pov="$(cpu "$POV")"; b_comp="$(cpu "$COMP")"
    wait "$WRITER"; wait "$POV"
    awk -v s="$SETTING" -v a="$a_pov" -v b="$b_pov" -v c="$a_comp" -v d="$b_comp" -v t="$T" -v k="$TCK" \
        'BEGIN { printf "[%s] pov_percent=%.2f compositor_percent=%.2f\n", s, 100 * (b - a) / k / t, 100 * (d - c) / k / t }' >> "$OUT"
    grep "^pov:" "$OUT.err" >> "$OUT"
done
unlink "$FIFO"
