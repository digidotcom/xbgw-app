# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import sys
import socket
from mock import Mock, patch, PropertyMock, call
import xbgw.xbee.io_sample

pubmock = Mock()
sockmock = Mock()
# Must be before UUT import
sockpatch = patch("socket.socket", sockmock)
pubpatch = patch("pubsub.pub", pubmock)
selectmock = Mock(name="selectmock")
# Shortcut to the return value of poll()
selectpatch = patch("xbgw.xbee.manager.select", selectmock)

# Hack these in before the manager import
socket.AF_XBEE = 98  # From NDS (exact value not important)
socket.XBS_PROT_TRANSPORT = 81  # See above
socket.XBS_PROT_APS = 82
socket.XBS_PROT_802154 = 83
socket.XBS_SOL_EP = 28  # From Python on XBee Gateway
socket.XBS_SO_EP_TX_STATUS = 20482  # See above
sys.modules['xbee'] = Mock()
sys.modules['rci_nonblocking'] = Mock()
sys.modules['select'] = selectmock
import xbgw.xbee.manager as manager
del sys.modules['xbee'], sys.modules['select'], sys.modules['rci_nonblocking']

from xbgw.settings.registry import SettingsRegistry

registry = None

def reset_mocks():
    pubmock.reset_mock()
    sockmock.reset_mock()


def setup():
    sockpatch.start()
    pubpatch.start()
    selectpatch.start()

    # Give XBeeEventManager poll object an integer for sock.fileno()
    sockmock.return_value.fileno.return_value = 0

    global registry
    registry = SettingsRegistry()


def teardown():
    sockpatch.stop()
    pubpatch.stop()
    selectpatch.stop()


# When UUT created, binds to 0xe8
def test_creation():
    manager.XBeeEventManager(registry)

    sockmock.assert_called_once_with(socket.AF_XBEE, socket.SOCK_DGRAM,
                                     socket.XBS_PROT_TRANSPORT)

    s = sockmock.return_value
    s.bind.assert_called_once_with(('', 0xe8, 0, 0))


def test_creation_bind_error():
    reset_mocks()
    s = sockmock.return_value

    def raise_ex(*args):
        import errno
        raise socket.error(errno.EOPNOTSUPP)

    # Save s.bind side effect to restore later
    old_se = s.bind.side_effect
    s.bind.side_effect = raise_ex

    try:
        uut = manager.XBeeEventManager(registry)
        assert uut.socket is None
        assert not uut.connected
    finally:
        s.bind.side_effect = old_se


# When an IO packet arrives, if it contains Analog data,
# publish to 'xbee.analog'
@patch("xbgw.xbee.io_sample.parse_is")
def do_analog(filtered, parsemock):
    reset_mocks()
    s = sockmock.return_value

    parsemock.side_effect = [
        {"AD0": 10},
        {"AD0": 11},
        {"AD0": 11},

        {"AD0": 12},
        {"AD0": 11},
        {"AD0": 10}
    ]

    fakeaddr = ('[00:11:22:33:44:55:66:77]!', 0xe8, 0xc105, 0x92)
    fakebuf = "Not important"
    s.recvfrom.return_value = (fakebuf, fakeaddr)

    settings = registry.get_by_binding("xbee_manager")
    settings['minimum_analog_change'] = 2
    settings['filter_analog_duplicates'] = filtered

    uut = manager.XBeeEventManager(registry)

    for _ in xrange(6):
        uut.handle_read()

    assert s.recvfrom.called

    if filtered:
        calls = [call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=10),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=12),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=10)]
    else:
        calls = [call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=10),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=11),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=11),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=12),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=11),
                 call('xbee.analog', ident=(fakeaddr[0], "AD0"), value=10)]

    pubmock.sendMessage.assert_has_calls(calls)


def test_analog():
    yield (do_analog, False)
    yield (do_analog, True)

# When an IO packet arrives, if it contains Digital data,
#   publish to 'xbee.digitalIn'
@patch("xbgw.xbee.io_sample.parse_is")
def do_digital(filtered, parsemock):
    reset_mocks()
    s = sockmock.return_value

    parsemock.side_effect = [{"DIO0": 0}, {"DIO0": 0}, {"DIO0": 1}]

    fakeaddr = ('[00:11:22:33:44:55:66:77]!', 0xe8, 0xc105, 0x92)
    fakebuf = "Not important"
    s.recvfrom.return_value = (fakebuf, fakeaddr)

    settings = registry.get_by_binding("xbee_manager")
    settings['filter_digital_duplicates'] = filtered

    uut = manager.XBeeEventManager(registry)

    for _ in xrange(3):
        uut.handle_read()

    assert s.recvfrom.called

    if filtered:
        calls = [call('xbee.digitalIn', ident=(fakeaddr[0], "DIO0"), value=0),
                 call('xbee.digitalIn', ident=(fakeaddr[0], "DIO0"), value=1)]
    else:
        calls = [call('xbee.digitalIn', ident=(fakeaddr[0], "DIO0"), value=0),
                 call('xbee.digitalIn', ident=(fakeaddr[0], "DIO0"), value=0),
                 call('xbee.digitalIn', ident=(fakeaddr[0], "DIO0"), value=1)]

    pubmock.sendMessage.assert_has_calls(calls)


def test_digital():
    yield (do_digital, True)
    yield (do_digital, False)


# When a serial packet arrives, publish to 'xbee.serialIn'
def test_serialIn():
    reset_mocks()
    s = sockmock.return_value

    fakeaddr = ('[00:11:22:33:44:55:66:77]!', 0xe8, 0xc105, 0x11)
    fakebuf = "Hello World"
    s.recvfrom.return_value = (fakebuf, fakeaddr)

    uut = manager.XBeeEventManager(registry)

    uut.handle_read()

    assert s.recvfrom.called

    pubmock.sendMessage.assert_called_once_with('xbee.serialIn',
                                                ident=(fakeaddr[0],),
                                                value=fakebuf)


# When handle_error is called, handle_close should NOT be called. (We want to
# avoid closing the XBee socket when at all possible, while asyncore prefers to
# close the socket at the first indication of a problem)
def test_handle_error():
    reset_mocks()

    uut = Mock(wraps=manager.XBeeEventManager(registry))

    # Stub out asyncore.compact_traceback, which is used in handle_error,
    # rather than sys.exc_info, which is used in asyncore.compact_traceback,
    # because the latter would be much harder to stub in a way that leaves
    # asyncore happy.
    tb_return_value = (None, "t_value", "v_value", "tb_info")

    import asyncore

    with patch.object(asyncore, 'compact_traceback',
                      return_value=tb_return_value):
        uut.handle_error()
        assert not uut.handle_close.called


# writable() should return False
def test_writable():
    reset_mocks()

    uut = manager.XBeeEventManager(registry)

    assert not uut.writable()
