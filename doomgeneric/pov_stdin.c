// Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
//
// This program is free software; you can redistribute it and/or
// modify it under the terms of the GNU General Public License
// as published by the Free Software Foundation; either version 2
// of the License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// cosmergon-pov: the control input of every platform layer is stdin (see pov_control.h).

#include <errno.h>
#include <poll.h>
#include <unistd.h>

#include "pov_control.h"

// Control input: stdin. wait == 0 never blocks (poll), wait != 0 blocks until data or end.
int DG_ControlRead(unsigned char *buf, int max, int wait)
{
    for (;;)
    {
        ssize_t n;

        if (!wait)
        {
            struct pollfd pfd = { 0, POLLIN, 0 };
            int r = poll(&pfd, 1, 0);

            if (r < 0)
            {
                if (errno == EINTR)
                {
                    continue;
                }
                return -1;
            }
            if (r == 0)
            {
                return 0;
            }
        }
        n = read(0, buf, (size_t)max);
        if (n < 0)
        {
            if (errno == EINTR)
            {
                continue;
            }
            return -1;
        }
        if (n == 0)
        {
            return -1;
        }
        return (int)n;
    }
}
