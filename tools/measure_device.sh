#!/usr/bin/env bash
# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
# Measurement on the device. Two windows of equal length, one after the other:
#   A  without the POV window (what the desktop costs as it stands)
#   B  with the POV window, fed by tools/pov_walk.py
# CPU time is read from /proc/<pid>/stat (utime + stime) at both ends of each window, per process:
# the compositor, the terminal of the dashboard, the dashboard, and in B the POV program and its
# writer. Output: one line per process and window, CPU seconds and percent of one core.
#
#   bash tools/measure_device.sh <seconds> <out-file>
set -u
SECONDS_EACH="${1:?seconds}"
OUT="${2:?out file}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
HYPRLAND_INSTANCE_SIGNATURE="$(ls "$XDG_RUNTIME_DIR/hypr/" | head -1)"
export HYPRLAND_INSTANCE_SIGNATURE
TCK="$(getconf CLK_TCK)"

cpu() { # pid -> ticks (utime + stime); empty if the process is gone
    [ -n "$1" ] && [ -r "/proc/$1/stat" ] && sed 's/^.*) //' "/proc/$1/stat" | awk '{print $12 + $13}'
}
line() { # label window pid before after seconds
    awk -v l="$1" -v w="$2" -v p="$3" -v a="$4" -v b="$5" -v s="$6" -v t="$TCK" \
        'BEGIN { if (a == "" || b == "") { printf "%s window=%s pid=%s not measured\n", l, w, p; exit }
                 c = (b - a) / t; printf "%s window=%s pid=%s cpu_s=%.2f percent_of_core=%.2f\n", l, w, p, c, 100 * c / s }'
}

COMP="$(pgrep -x Hyprland | head -1)"
TERM_PID="$(hyprctl clients -j | python3 -c 'import json,sys; print(next((c["pid"] for c in json.load(sys.stdin) if c["class"] == "org.omarchy.cosmergon"), ""))')"
DASH=""
[ -n "$TERM_PID" ] && DASH="$(pgrep -P "$TERM_PID" | head -1)"
{
    echo "start=$(date -u +%FT%TZ) seconds_each=$SECONDS_EACH clk_tck=$TCK"
    echo "compositor=$COMP terminal=$TERM_PID dashboard=$DASH ($(tr '\0' ' ' < "/proc/${DASH:-0}/cmdline" 2>/dev/null | cut -c1-100))"
    echo "load_before=$(cut -d' ' -f1-3 /proc/loadavg)"
} > "$OUT"

# --- A
a_comp="$(cpu "$COMP")"; a_term="$(cpu "$TERM_PID")"; a_dash="$(cpu "$DASH")"
sleep "$SECONDS_EACH"
b_comp="$(cpu "$COMP")"; b_term="$(cpu "$TERM_PID")"; b_dash="$(cpu "$DASH")"
{
    line compositor A "$COMP" "$a_comp" "$b_comp" "$SECONDS_EACH"
    line terminal A "$TERM_PID" "$a_term" "$b_term" "$SECONDS_EACH"
    line dashboard A "$DASH" "$a_dash" "$b_dash" "$SECONDS_EACH"
    echo "load_after_A=$(cut -d' ' -f1-3 /proc/loadavg)"
} >> "$OUT"

# --- B
FIFO="$XDG_RUNTIME_DIR/cosmergon-pov-measure.fifo"
[ -p "$FIFO" ] || mkfifo -m 600 "$FIFO"
"$HERE/doomgeneric/cosmergon-pov" -iwad "$HERE/assets/freedoom/freedoom1.wad" -file "$HERE/assets/cosmergon.wad" \
    -pov-control < "$FIFO" > /dev/null 2> "$OUT.pov-stderr" &
POV=$!
python3 "$HERE/tools/pov_walk.py" "$SECONDS_EACH" > "$FIFO" &
WRITER=$!
sleep 1
a_comp="$(cpu "$COMP")"; a_term="$(cpu "$TERM_PID")"; a_dash="$(cpu "$DASH")"; a_pov="$(cpu "$POV")"; a_wr="$(cpu "$WRITER")"
T=$((SECONDS_EACH - 3))
sleep "$T"
b_comp="$(cpu "$COMP")"; b_term="$(cpu "$TERM_PID")"; b_dash="$(cpu "$DASH")"; b_pov="$(cpu "$POV")"; b_wr="$(cpu "$WRITER")"
{
    line compositor B "$COMP" "$a_comp" "$b_comp" "$T"
    line terminal B "$TERM_PID" "$a_term" "$b_term" "$T"
    line dashboard B "$DASH" "$a_dash" "$b_dash" "$T"
    line pov B "$POV" "$a_pov" "$b_pov" "$T"
    line writer B "$WRITER" "$a_wr" "$b_wr" "$T"
} >> "$OUT"
wait "$WRITER"
wait "$POV"
echo "pov_exit=$?" >> "$OUT"
unlink "$FIFO"
{
    cat "$OUT.pov-stderr"
    echo "load_after_B=$(cut -d' ' -f1-3 /proc/loadavg)"
    echo "end=$(date -u +%FT%TZ)"
} >> "$OUT"
