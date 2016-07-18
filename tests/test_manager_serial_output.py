# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from mock import Mock, patch
from nose.tools import with_setup, eq_
import socket
import sys
import base64
from xml.etree.ElementTree import Element
from util import assert_command_error

from hamcrest.library.integration import match_equality
from hamcrest import instance_of, assert_that, has_item, starts_with, equal_to

sockmock = Mock()
sockpatch = patch("socket.socket", sockmock)
selectmock = Mock(name="selectmock")
# Shortcut to the return value of poll()
selectpatch = patch("xbgw.xbee.manager.select", selectmock)
xbeemock = Mock()
xbeepatch = patch("xbgw.xbee.manager.xbee", xbeemock)

# Don't import the actual socket module
# Hack these in before the manager import
socket.AF_XBEE = 98  # From NDS (exact value not important)
socket.XBS_PROT_TRANSPORT = 81  # See above
socket.XBS_PROT_APS = 82
socket.XBS_PROT_802154 = 83
socket.XBS_SOL_EP = 28  # From Python on XBee Gateway
socket.XBS_SO_EP_TX_STATUS = 20482  # See above
# Don't import the actual socket or xbee modules
sys.modules['xbee'] = xbeemock
# In case the testing OS doesn't support poll
sys.modules['select'] = selectmock
sys.modules['rci_nonblocking'] = Mock()  # Needed by command processor
from xbgw.xbee.manager import XBeeEventManager, errors
from xbgw.xbee.manager import SocketUnavailable
from xbgw.command.rci import ResponsePending, DeferredResponse
del sys.modules['select']
del sys.modules['rci_nonblocking']
del sys.modules['xbee']


from xbgw.xbee.utils import normalize_ieee_address
from xbgw.settings.registry import SettingsRegistry

registry = None

from util import get_pubsub_listener


def _setup():
    sockmock.reset_mock()
    sockpatch.start()
    selectpatch.start()

    global registry
    registry = SettingsRegistry()

def _teardown():
    sockpatch.stop()
    selectpatch.stop()


# Decorator for generated test case functions, to ensure the socket.socket
# patch is run correctly, as well as the patching of the select module.
patches_socket_and_select = with_setup(_setup, _teardown)


def get_listener(pubmock):
    """
    Find and return the "command.send_serial" listener subscribed to
    the given pubsub.pub mock.
    """
    return get_pubsub_listener(pubmock, "command.send_serial")


# Test that when a text string is sent, that it is successfully
# sent to the XBee specified.
@patches_socket_and_select
def do_send_serial(pubmock, attrs, encoded_data, transmit_data,
                   expected_addr=None):
    expected_addr = expected_addr or attrs['addr']
    pubmock.reset_mock()
    mgr = XBeeEventManager(registry)
    pollermock = mgr.poller
    pollermock.poll.return_value = [(mgr.socket.fileno.return_value,
                                     selectmock.POLLOUT)]

    # Get the listener from subscribe's last call
    listener = get_listener(pubmock)
    assert listener is not None

    # Create command object
    el = Element("send_serial", attrib=attrs)
    el.text = encoded_data

    rsp = Mock()
    listener(element=el, response=rsp)
    mgr.socket.sendto.assert_called_once_with(transmit_data,
                                (expected_addr,
                                 0xe8,
                                 0xc105,
                                 0x11,
                                 0,
                                 match_equality(instance_of(int))))

    # Grab the transmit identifier so we can complete it
    # First call, second argument, sixth member of address tuple
    tx_id = mgr.socket.sendto.call_args[0][1][5]

    rsp.put.assert_called_once_with(ResponsePending)
    rsp.reset_mock()

    # Trigger completion with transmit status
    mgr.socket.recvfrom.return_value = (
        # TX Status response, frame info, dst, and other indicators all success
        '\x8b\x00\x00\x00\x00\x00\x00',
        ('[00:00:00:00:00:00:00:00]!',
         0x0, 0xc105, 0x8b, 0x0, tx_id))

    # Tell dispatcher portion that it has data
    mgr.handle_read()

    rsp.put.assert_called_once_with(
        match_equality(instance_of(DeferredResponse)))
    # First call, only arg
    dr = rsp.put.call_args[0][0]
    print dr

    assert "error" not in dr.response.keys()
    assert dr.response.text == ""


def test_send_serial_success():
    addr = '[00:11:22:33:44:55:66:77]!'
    BINARY_STRING = ''.join([chr(i) for i in xrange(256)])
    UNICODE_STRING = u"I have Unicode data: \u1234"
    ASCII_STRING = ''.join([chr(i) for i in xrange(128)])

    with patch("xbgw.xbee.manager.pubsub.pub") as pubmock:
        # Default encoding (base64)
        yield (do_send_serial, pubmock,
               {"addr": addr}, base64.b64encode(BINARY_STRING), BINARY_STRING)

        # Base64 explicitly specified
        yield (do_send_serial, pubmock,
               {"addr": addr, "encoding": "base64"},
               base64.b64encode(BINARY_STRING), BINARY_STRING)

        # UTF-8 - with multiple byte codepoints
        # ElementTree will turn this into a Unicode string, we need to
        # ensure that it is *re-encoded* into UTF-8 properly when the
        # send occurs
        yield (do_send_serial, pubmock,
               {"addr": addr, "encoding": "utf-8"},
               UNICODE_STRING, UNICODE_STRING.encode("utf-8"))

        # UTF-8 - ASCII subset
        # The above behavior will pass through the UTF-8 encoder,
        # check that it does so cleanly
        yield (do_send_serial, pubmock,
               {"addr": addr, "encoding": "utf-8"},
               ASCII_STRING, ASCII_STRING)

        # Does it recognize broadcast
        yield (do_send_serial, pubmock,
               {"addr": "broadcast"},
               base64.b64encode(BINARY_STRING), BINARY_STRING,
               "[00:00:00:00:00:00:FF:FF]!")


# When we run out of TX IDs, report an error
@patches_socket_and_select
@patch("xbgw.xbee.manager.pubsub.pub")
def test_tx_id_exhaustion(pubmock):
    pubmock.reset_mock()

    attrs = {"addr": "0011223344556677"}

    mgr = XBeeEventManager(registry)
    pollermock = mgr.poller
    pollermock.poll.return_value = [(mgr.socket.fileno.return_value,
                                     selectmock.POLLOUT)]

    # Get the listener from subscribe's last call
    listener = get_listener(pubmock)
    assert listener is not None

    # Create command object
    el = Element("send_serial", attrib=attrs)
    el.text = "1234"

    rsp = Mock()
    for _ in xrange(255):
        listener(element=el, response=rsp)
        eq_(rsp.put.call_count, 1)
        rsp.put.assert_called_once_with(ResponsePending)
        rsp.reset_mock()

    # tx_callbacks should contain entries for range [1,255] inclusive

    # Push it over the limit
    listener(element=el, response=rsp)
    eq_(rsp.put.call_count, 1)
    r = rsp.put.call_args[0][0]

    assert_command_error(r, "Too many outstanding transmits")


# Test that when a text string is sent, that an error occurs
@patches_socket_and_select
def do_send_serial_error(pubmock, attrs, data, error_prefix, error_hint=None,
                         tx_status_err=0, send_exc=None, fileno_val=0):
    pubmock.reset_mock()
    mgr = XBeeEventManager(registry)
    pollermock = mgr.poller

    if fileno_val:
        fno_return = fileno_val
    else:
        fno_return = mgr.socket.fileno.return_value

    pollermock.poll.return_value = [(fno_return,
                                     selectmock.POLLOUT)]

    # Get the listener from subscribe's last call
    listener = get_listener(pubmock)
    assert listener is not None

    # Create command object
    el = Element("send_serial", attrib=attrs)
    el.text = data

    if send_exc:
        mgr.socket.sendto.side_effect = send_exc

    rsp = Mock()
    listener(element=el, response=rsp)

    if send_exc:
        mgr.socket.sendto.side_effect = None

    if not tx_status_err:
        assert_that(rsp.put.call_count, equal_to(1))
        r = rsp.put.call_args[0][0]
        rsp.put.assert_called_once_with(match_equality(instance_of(Element)))
        # Only call, only arg is hopeful error element
        el = rsp.put.call_args[0][0]
        assert_command_error(el, error_prefix, error_hint)

        return

    #### Deal only with tx_status errors beyond here

    # Grab the transmit identifier so we can comlete it
    # First call, second argument, sixth member of address tuple
    tx_id = mgr.socket.sendto.call_args[0][1][5]

    rsp.put.assert_called_once_with(ResponsePending)
    rsp.reset_mock()

    # Trigger completion with transmit status
    mgr.socket.recvfrom.return_value = (
        # TX Status response, frame info, dst, and other
        # indicators all success
        '\x8b\x00\x00\x00\x00' + chr(tx_status_err) + '\x00',
        ('[00:00:00:00:00:00:00:00]!',
         0x0, 0xc105, 0x8b, 0x0, tx_id))

    print mgr.socket.recvfrom.return_value

    # Tell dispatcher portion that it has data
    mgr.handle_read()

    rsp.put.assert_called_once_with(
        match_equality(instance_of(DeferredResponse)))
    # First call, only arg
    dr = rsp.put.call_args[0][0]
    el = dr.response
    assert_command_error(el, error_prefix, error_hint)


def test_send_serial_error():
    addr = "0011223344556677"
    with patch("xbgw.xbee.manager.pubsub.pub") as pubmock:
        # Missing addr
        yield (do_send_serial_error,
               pubmock, {}, 'aaaa',
               errors['missingattr'], "No destination XBee address")

        # Unrecognized encoding
        yield (do_send_serial_error,
               pubmock, {"addr": addr, "encoding": "unknown"}, 'aaaa',
               errors['encoding'])

        # Specified base64, but isn't (not padded right)
        yield (do_send_serial_error,
               pubmock, {"addr": addr, "base64": "unknown"}, 'aaa',
               errors['base64'])

        # ValueError from normalize_ieee
        ## Address too short or not hex (containing hex is okay) :-(
        yield (do_send_serial_error,
               pubmock, {"addr": "NONHX"}, 'aaaa',
               errors['address'], "Address is too short")

        ## Address too long
        yield (do_send_serial_error,
               pubmock, {"addr": "11223344556677889900"}, 'aaaa',
               errors['address'], "Address is too long")

        # TypeError from normalize_ieee (send other than string,
        # int or long) Can't happen in current system, always get
        # strings from ET

        # UnicodeEncodeError (not really utf-8) We can pass in bogus
        # data that we don't expect to be allowed to us, does that
        # help? Probably doesn't make sense as long as ET is feeding
        # us, as above.

        # Message too long
        yield (do_send_serial_error,
               pubmock, {"addr": "1234"}, 'a' * 128,
               errors['txfailed'], None,
               0, socket.error("[Errno 90]"))

        # TX Status error
        yield (do_send_serial_error,
               pubmock, {"addr": "1234"}, 'aaaa',
               errors['txstatus'], "0x01: MAC ACK Failure", 1)

        # Unknown TX Status Error
        yield (do_send_serial_error,
               pubmock, {"addr": "1234"}, 'aaaa',
               errors['txstatus'], "0x03: Unknown", 3)

        # Poll fails (fileno will not match the mock)
        yield (do_send_serial_error,
               pubmock, {"addr": "1234"}, 'aaaa',
               errors['txfailed'], None, 0, None, 99)
