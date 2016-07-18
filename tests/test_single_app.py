# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import fcntl
import os.path
import sys
import socket

from mock import Mock, patch

from hamcrest import instance_of, assert_that, equal_to
from hamcrest.library.integration import match_equality

# Don't import the actual socket module
# Hack these in before the manager import
socket.AF_XBEE = 98  # From NDS (exact value not important)
socket.XBS_PROT_TRANSPORT = 81  # See above
socket.XBS_PROT_APS = 82
socket.XBS_PROT_802154 = 83
socket.XBS_SOL_EP = 28  # From Python on XBee Gateway
socket.XBS_SO_EP_TX_STATUS = 20482  # See above
socket.XBS_STAT_OK = 0
socket.XBS_STAT_ERROR = 1
socket.XBS_STAT_BADCMD = 2
socket.XBS_STAT_BADPARAM = 3
socket.XBS_STAT_TXFAIL = 4
sys.modules["xbee"] = Mock()
sys.modules["rci_nonblocking"] = Mock()
sys.modules['idigidata'] = Mock()
import xbgw_main as dut
del sys.modules["xbee"], sys.modules["rci_nonblocking"]
del sys.modules['idigidata']


@patch("logging.getLogger")
@patch("atexit.register")
@patch("os.ftruncate")
@patch("sys.exit")
@patch("fcntl.flock")
def test_success(flockmock, exitmock, truncatemock, atexitmock, logmock):
    # When we attempt to acquire a lock on 'PID_FILE', the acquisition
    # suceeds, file is created, and we arrange for it to be
    # removed.

    dut.PID_FILE = "test.pid"
    if (os.path.exists(dut.PID_FILE)):
        # Make sure file does not exist as a precondition
        os.remove(dut.PID_FILE)

    dut.prevent_duplicate(dut.PID_FILE)

    # Always expect to interact with flock()
    flockmock.assert_called_once_with(match_equality(instance_of(file)),
                                      match_equality(
                                          fcntl.LOCK_EX | fcntl.LOCK_NB))

    # The road not taken
    assert_that(exitmock.call_count, equal_to(0))
    assert_that(logmock.return_value.error.call_count, equal_to(0))

    # Assertions to prove we took the happy path
    truncatemock.assert_called_once_with(
        match_equality(instance_of(int)),
        match_equality(0))
    atexitmock.assert_called_once_with(
        match_equality(dut.cleanup_pidfile),
        match_equality(instance_of(file)))

    assert(os.path.exists(dut.PID_FILE))

    # Clean up
    os.remove(dut.PID_FILE)


@patch("logging.getLogger")
@patch("atexit.register")
@patch("os.ftruncate")
@patch("sys.exit")
@patch("fcntl.flock")
def test_error(flockmock, exitmock, truncatemock, atexitmock, logmock):
    # When we attempt to acquire a lock on 'PID_FILE', the acquisition
    # fails, Log issue and exit.
    dut.PID_FILE = "test.pid"
    if (os.path.exists(dut.PID_FILE)):
        # Make sure file does not exist as a precondition
        os.remove(dut.PID_FILE)

    # Arrange error return from locking mock
    flockmock.side_effect = IOError
    exitmock.side_effect = SystemExit

    try:
        dut.prevent_duplicate(dut.PID_FILE)
    except SystemExit:
        pass  # Expected from exitmock

    # Always expect to interact with flock()
    flockmock.assert_called_once_with(match_equality(instance_of(file)),
                                      match_equality(
                                          fcntl.LOCK_EX | fcntl.LOCK_NB))

    # Assertions to prove we took the un-happy path
    exitmock.assert_called_once_with(-1)
    logmock.return_value.error.assert_called_once_with(
        match_equality(instance_of(str)))

    # The road not taken
    assert_that(truncatemock.call_count, equal_to(0))
    assert_that(atexitmock.call_count, equal_to(0))

    assert(os.path.exists(dut.PID_FILE))
    os.remove(dut.PID_FILE)
