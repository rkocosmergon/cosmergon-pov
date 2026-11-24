# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
# Source this file: provides run_limited <seconds> <command> [args...].
# A bounded wait with shell built-ins only (no `timeout`, which macOS does not ship); runs on bash 3.2.
# Same exit code as the command. When the limit is over the command gets TERM, after one second KILL,
# the message "run_limited: ... killed after N s" goes to stderr and the exit code is 124 (as GNU timeout).
# stdin, stdout and stderr are the caller's (a background job of a script would otherwise lose stdin).
run_limited() {
    local limit="$1" pid waited=0 rc
    shift
    "$@" <&0 &
    pid=$!
    while kill -0 "${pid}" 2>/dev/null; do
        if [ "${waited}" -ge $((limit * 5)) ]; then
            echo "run_limited: '$1' killed after ${limit} s" >&2
            kill -TERM "${pid}" 2>/dev/null
            sleep 1
            kill -KILL "${pid}" 2>/dev/null
            wait "${pid}" 2>/dev/null
            return 124
        fi
        sleep 0.2
        waited=$((waited + 1))
    done
    wait "${pid}"
    rc=$?
    return "${rc}"
}
