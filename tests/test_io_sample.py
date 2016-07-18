# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import struct

from xbgw.xbee.io_sample import parse_is


def test_parse_is():
    # Very basic test, primarily to ensure that we have some minimal
    # run-time coverage on this code that was pulled in from DIA. This
    # is legacy code that has run successfully for a very long time in
    # DIA before coming here.
    fmt = "!BHBHHHHH"
    s = struct.pack(fmt,
                    0x01, 0xfff0, 0x0f, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff)
    d = parse_is(s)

    for i in xrange(4):
        assert("AD" + str(i) in d)

    for i in xrange(4, 16):
        assert("DIO" + str(i) in d)
