# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""\
    A simple parser for XBee I/O samples.

    Most XBee devices support retrieving of both Analog and Digital
    samples from the device.
    This is done by issuing the DDO 'IS' command, in which the unit
    will pack its AIO and DIO values into the response.

    This file offers a helper function to decode the response for the user.

"""

import struct


def parse_is(data):
    """\
        Parse the response of the XBee DDO 'IS' command.

        Returns a dictionary of values keyed with each DIO or AD channel found.
    """

    ## We need to differentiate between series 1 and series 2 formats.
    ## The series 1 format should always return a 'odd' byte count eg 7, 9, 11
    ## or 13 bytes. The series 2 format should always return a 'even' byte
    ## count eg, 8, 10, 12 or 14 bytes. So we mod 2 the length, 0 is series 2,
    ## 1 is series 1.

    if len(data) % 2 == 0:
        _, datamask, analogmask = struct.unpack("!BHB", data[:4])
        data = data[4:]

    else:
        _, mask = struct.unpack("!BH", data[:3])
        data = data[3:]
        datamask = mask % 512  # Move the first 9 bits into a separate mask
        analogmask = mask >> 9  # Move the last 7 bits into a separate mask

    retdir = {}

    if datamask:
        datavals = struct.unpack("!H", data[:2])[0]
        data = data[2:]

        currentDI = 0
        while datamask:
            if datamask & 1:
                retdir["DIO%d" % currentDI] = bool(datavals & 1)
            datamask >>= 1
            datavals >>= 1
            currentDI += 1

    currentAI = 0
    while analogmask:
        if analogmask & 1:

            aval = struct.unpack("!H", data[:2])[0]
            data = data[2:]

            retdir["AD%d" % currentAI] = aval
        analogmask >>= 1
        currentAI += 1

    return retdir
