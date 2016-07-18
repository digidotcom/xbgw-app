# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from mock import Mock, patch
from nose.tools import with_setup, eq_
from hamcrest.library.integration import match_equality
from hamcrest import instance_of
import socket
import struct
import sys
from xml.etree.ElementTree import Element, tostring

from util import assert_command_error

sockmock = Mock()
sockpatch = patch("socket.socket", sockmock)
selectmock = Mock(name="selectmock")
# Shortcut to the return value of poll()
selectpatch = patch("xbgw.xbee.ddo_manager.select", selectmock)
xbeemock = Mock()

# Don't import the actual socket module
# Hack these in before the manager import
socket.AF_XBEE = 98  # From NDS (exact value not important)
socket.XBS_PROT_TRANSPORT = 81  # See above
socket.XBS_PROT_APS = 82
socket.XBS_PROT_802154 = 83
socket.XBS_PROT_DDO = 85
socket.XBS_SOL_EP = 28  # From Python on XBee Gateway
socket.XBS_SO_EP_TX_STATUS = 20482  # See above
socket.XBS_OPT_DDO_APPLY = 2
# transmit status codes
socket.XBS_STAT_OK = 0
socket.XBS_STAT_ERROR = 1
socket.XBS_STAT_BADCMD = 2
socket.XBS_STAT_BADPARAM = 3
socket.XBS_STAT_TXFAIL = 4
# Don't import the actual xbee module
sys.modules['xbee'] = xbeemock
sys.modules['rci_nonblocking'] = Mock()
# In case the testing OS doesn't support poll
sys.modules['select'] = selectmock
from xbgw.xbee.ddo_manager import DDOEventManager, errors
del sys.modules['xbee'], sys.modules['select'], sys.modules['rci_nonblocking']

from xbgw.xbee.utils import normalize_ieee_address
from xbgw.command.rci import ResponsePending, DeferredResponse

from util import MatchCallable, get_pubsub_listener


def _setup():
    sockmock.reset_mock()
    xbeemock.reset_mock()
    sockpatch.start()
    selectpatch.start()


def _teardown():
    sockpatch.stop()
    selectpatch.stop()


# Decorator for generated test case functions, to ensure the socket.socket
# patch is run correctly, as well as the patching of the select module.
patches_socket_and_select = with_setup(_setup, _teardown)


# Shorthand for patch("xbgw.xbee.ddo_manager.pubsub.pub")
# (Typing that out in each test method can be tiring)
make_pubmock = lambda: patch("xbgw.xbee.ddo_manager.pubsub.pub")


def get_dout_listener(pubmock):
    """
    Find and return the "command.set_digital_output" listener subscribed to
    the given pubsub.pub mock.
    """
    return get_pubsub_listener(pubmock, "command.set_digital_output")


# When UUT is created, it subscribes something to "command.set_digital_output"
@patches_socket_and_select
@patch("xbgw.xbee.ddo_manager.pubsub.pub")
def test_digital_output_creation(pubmock):
    DDOEventManager()
    # Ensure that a socket is created
    sockmock.assert_called_once_with(socket.AF_XBEE, socket.SOCK_DGRAM,
                                     socket.XBS_PROT_DDO)
    # Ensure that the manager subscribes to set_digital_output command
    pubmock.subscribe.assert_any_call(MatchCallable(),
                                      "command.set_digital_output")


@patches_socket_and_select
def do_error_starts_with(pubmock, message, attrs={}, text="", hint=None):
    pubmock.reset_mock()
    DDOEventManager()

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    el = Element("set_digital_output", attrib=attrs)
    el.text = text

    response = Mock()
    listener(element=el, response=response)

    eq_(response.put.call_count, 1)

    # Extract the listener's response
    r = response.put.call_args[0][0]
    assert_command_error(r, message, hint)

    # Check that we never reached the socket.sendto call
    assert not sockmock.return_value.sendto.called


# Simple helper method for the do_successful_* test methods.
def helper_do_successful(pubmock, attrs, text, call_setting, call_value):
    pubmock.reset_mock()
    mgr = DDOEventManager()

    pollermock = mgr.poller
    pollermock.poll.return_value = [(mgr.socket.fileno.return_value,
                                     selectmock.POLLOUT)]

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    el = Element("set_digital_output", attrib=attrs)
    el.text = text

    response = Mock()
    listener(element=el, response=response)

    # Check that ResponsePending was placed on the queue
    response.put.assert_called_once_with(ResponsePending)
    response.reset_mock()

    # Check the socket call was made correctly.
    addr = attrs['addr']
    normalized_addr = normalize_ieee_address(addr)

    sendto = sockmock.return_value.sendto

    payload = struct.pack('!I', call_value)

    sendto.assert_called_once_with(
        payload,
        (normalized_addr, call_setting, socket.XBS_OPT_DDO_APPLY,
         match_equality(instance_of(int))))

    # Grab the transmission ID so we can present a status frame
    tx_id = sendto.call_args[0][1][3]

    sockmock.return_value.recvfrom.return_value = (
        "",
        ('[00:00:00:00:00:00:00:00]!', call_setting, socket.XBS_OPT_DDO_APPLY,
         tx_id, 0)
    )

    # Tell dispatcher portion that it has data
    mgr.handle_read()

    response.put.assert_called_once_with(
        match_equality(instance_of(DeferredResponse)))
    # Extract response. First call, only arg.
    deferred_resp = response.put.call_args[0][0]

    assert "error" not in deferred_resp.response.keys()
    assert deferred_resp.response.text == ""


@patches_socket_and_select
def do_successful_set(pubmock, addr, index, text, call_setting, call_value):
    helper_do_successful(pubmock, {"addr": addr, "index": index}, text,
                         call_setting, call_value)


@patches_socket_and_select
def do_successful_set_name(pubmock, addr, name, text, call_setting, call_val):
    helper_do_successful(pubmock, {"addr": addr, "name": name}, text,
                         call_setting, call_val)


# When the set_digital_output listener is called, it will respond with an error
# if the element has no 'addr' attribute.
def test_digital_output_no_addr_handling():
    msg = "No destination XBee"
    with make_pubmock() as pubmock:
        yield do_error_starts_with, pubmock, errors['missingattr'], {}, "", msg
        yield (do_error_starts_with,
               pubmock, errors['missingattr'], {"addr": None}, "", msg)


# Respond with an error if the address cannot be normalized properly (too
# short, too long, etc.)
def test_digital_output_bad_addr_handling():
    with make_pubmock() as pubmock:
        # Too short
        attrs = {'addr': 'zyxw'}  # No hexadecimal digits
        yield (do_error_starts_with,
               pubmock, errors['address'], attrs, "", "Address is too short")

        # Too long
        attrs = {'addr': '0011223344556677abcd'}
        yield (do_error_starts_with,
               pubmock, errors['address'], attrs, "Address is too long")


# When the set_digital_output listener is called, it will respond with an error
# if the element has no index attribute, or that attribute is empty.
def test_digital_output_no_index_handling():
    msg = "No digital output pin number"
    addr = "00:40:9d:ff:ff:ff:ff:ff"
    with make_pubmock() as pubmock:
        yield (do_error_starts_with,
               pubmock, errors['missingattr'], {"addr": addr}, "", msg)
        yield (do_error_starts_with,
               pubmock, errors['missingattr'],
               {"addr": addr, "index": None}, "",
               msg)


# When the set_digital_output listener is called, it will respond with an error
# if the index is out of the range 0-12, or did not represent a valid int.
# It also will respond with an error if the index is 9.
# TODO: Update DIO9-related test when we have to handle 802.15.4 as well as ZB.
# (ZB products use the DIO9 pin, while 802.15.4 makes it available.)
def test_digital_output_bad_index_handling():
    msg = "Pin number ('index') must be"
    dio9msg = "DIO9 cannot be configured for digital"
    address = "77:66:55:44:33:22:11:00"
    mkattrs = lambda index: {"addr": address, "index": str(index)}

    with make_pubmock() as pubmock:
        yield (do_error_starts_with,
               pubmock, errors['invalidattr'], mkattrs(-1), msg)
        yield (do_error_starts_with,
               pubmock, errors['invalidattr'], mkattrs(-500), msg)
        yield (do_error_starts_with,
               pubmock, errors['invalidattr'], mkattrs(13), msg)
        yield (do_error_starts_with,
               pubmock, errors['invalidattr'], mkattrs(5000), msg)
        yield (do_error_starts_with,
               pubmock, errors['invalidattr'], mkattrs("foo"), msg)
        yield (do_error_starts_with,
               pubmock, errors['invalidattr'], mkattrs(9), dio9msg)


# When the set_digital_output command is sent, with both name and index
# attributes specified, the response should indicate an appropriate error.
def test_digital_output_both_name_and_index():
    msg = errors['toomanyattrs']
    hint = "Must specify only an index or a name, not both."
    mkattrs = lambda index, name: {
        "addr": "00:11:22:33:44:55:66:77", "index": str(index),
        "name": name
    }

    with make_pubmock() as pubmock:
        # manager should catch this error, whether or not the name and index
        # match up.
        yield do_error_starts_with, pubmock, msg, mkattrs(0, "D0"), hint
        yield do_error_starts_with, pubmock, msg, mkattrs(0, "DIO1"), hint
        yield do_error_starts_with, pubmock, msg, mkattrs(1, "D4"), hint
        yield do_error_starts_with, pubmock, msg, mkattrs(100, "P0"), hint


# When the set_digital_output command is sent, with a name given (to specify
# the digital output to change), unrecognized names should signal an error.
def test_digital_output_bad_name_handling():
    msg = errors['invalidattr']
    hint = "Unrecognized digital output name"
    addr = "00:11:22:33:44:55:66:77"
    mkattrs = lambda name: {"addr": addr, "name": name}

    with make_pubmock() as pubmock:
        # D0 through D9 are valid
        yield do_error_starts_with, pubmock, msg, mkattrs("D10"), hint
        # Completely unrecognized names
        yield do_error_starts_with, pubmock, msg, mkattrs("foobar"), hint
        yield do_error_starts_with, pubmock, msg, mkattrs("D00"), hint
        yield do_error_starts_with, pubmock, msg, mkattrs("P3"), hint
        # Recognized as bad (i.e. names for pins, but not related to digital)
        yield do_error_starts_with, pubmock, msg, mkattrs("ASSOC")
        yield do_error_starts_with, pubmock, msg, mkattrs("PWM0")
        yield do_error_starts_with, pubmock, msg, mkattrs("AD1")
        yield do_error_starts_with, pubmock, msg, mkattrs("RTS")
        yield do_error_starts_with, pubmock, msg, mkattrs("PWM")
        yield do_error_starts_with, pubmock, msg, mkattrs("P1")
        yield do_error_starts_with, pubmock, msg, mkattrs("SLEEP_RQ")


# When the listener is called, it should respond with an error if the value
# (text inside the element) cannot be parsed properly (using distutils
# strtobool)
def test_digital_output_bad_value_handling():
    msg = errors['badoutput']
    attrs = {"addr": "77:66:55:44:33:22:11:00", "index": 5}
    with make_pubmock() as pubmock:
        yield do_error_starts_with, pubmock, msg, attrs, "fals"
        yield do_error_starts_with, pubmock, msg, attrs, "nope"
        yield do_error_starts_with, pubmock, msg, attrs, "nah"
        yield do_error_starts_with, pubmock, msg, attrs, "sure"
        yield do_error_starts_with, pubmock, msg, attrs, "yep"
        yield do_error_starts_with, pubmock, msg, attrs, "why not"


# Tests for the proper interaction with command.set_digital_out on pubsub, when
# the command is properly formed.
def test_digital_output_good_using_index():
    with make_pubmock() as pubmock:
        # Numeric values
        yield do_successful_set, pubmock, "01f", "0", "1", "D0", 5
        yield do_successful_set, pubmock, "01f", "5", "1", "D5", 5
        yield do_successful_set, pubmock, "01f", "1", "0", "D1", 4
        yield do_successful_set, pubmock, "01f", "5", "0", "D5", 4
        yield do_successful_set, pubmock, "01f", "12", "0", "P2", 4

        # Values strtobool understands
        yield do_successful_set, pubmock, "01e", "12", "y", "P2", 5
        yield do_successful_set, pubmock, "01e", "12", "yes", "P2", 5
        yield do_successful_set, pubmock, "01e", "12", "true", "P2", 5
        yield do_successful_set, pubmock, "01e", "12", "on", "P2", 5
        yield do_successful_set, pubmock, "01e", "12", "n", "P2", 4
        yield do_successful_set, pubmock, "01e", "12", "no", "P2", 4
        yield do_successful_set, pubmock, "01e", "12", "false", "P2", 4
        yield do_successful_set, pubmock, "01e", "12", "off", "P2", 4

        # "low" and "high"
        yield do_successful_set, pubmock, "ba0", "12", "high", "P2", 5
        yield do_successful_set, pubmock, "ba0", "12", "low", "P2", 4


# Tests for the proper interaction with command.set_digital_out on pubsub, when
# the command is properly formed.
def test_digital_output_good_using_name():
    with make_pubmock() as pubmock:
        # Numeric values
        # (Not all valid output names are represented here - just a
        # representative subset of them.)
        yield do_successful_set_name, pubmock, "01f", "D0", "1", "D0", 5
        yield do_successful_set_name, pubmock, "01f", "DIO5", "1", "D5", 5
        yield do_successful_set_name, pubmock, "01f", "D5", "0", "D5", 4
        yield do_successful_set_name, pubmock, "01f", "DIO11", "0", "P1", 4
        # 9 (D9, ON, SLEEP, DIO9, etc.) is an invalid pin index to set, so we
        # skip testing it here.

        # Values strtobool understands
        yield do_successful_set_name, pubmock, "01e", "DIO12", "y", "P2", 5
        yield do_successful_set_name, pubmock, "01e", "DIO12", "yes", "P2", 5
        yield do_successful_set_name, pubmock, "01e", "DIO12", "true", "P2", 5
        yield do_successful_set_name, pubmock, "01e", "DIO12", "on", "P2", 5
        yield do_successful_set_name, pubmock, "01e", "DIO12", "n", "P2", 4
        yield do_successful_set_name, pubmock, "01e", "DIO12", "no", "P2", 4
        yield do_successful_set_name, pubmock, "01e", "DIO12", "false", "P2", 4
        yield do_successful_set_name, pubmock, "01e", "DIO12", "off", "P2", 4

        # "low" and "high"
        yield do_successful_set_name, pubmock, "ba0", "DIO12", "high", "P2", 5
        yield do_successful_set_name, pubmock, "ba0", "DIO12", "low", "P2", 4


# If the sendto call raises an Exception, the message of that exception
# shall be set as the error message of the response.
@patches_socket_and_select
@patch("xbgw.xbee.ddo_manager.pubsub.pub")
def test_with_raised_error(pubmock):
    DDOEventManager()

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    el = Element("set_digital_output")
    el.set("addr", "0011223344556677")
    el.set("index", "5")
    el.text = "on"

    old_se = sockmock.return_value.sendto.side_effect

    sockmock.return_value.sendto.side_effect = Exception("-- exc --")

    response = Mock()
    listener(element=el, response=response)

    assert response.put.call_count == 1
    assert sockmock.return_value.sendto.called

    # Extract the listener's response
    r = response.put.call_args[0][0]
    print tostring(r)
    assert_command_error(r, errors['txfailed'],
                         sockmock.return_value.sendto.side_effect.message)

    # Reset the side effect
    sockmock.return_value.sendto.side_effect = old_se


@patches_socket_and_select
@patch("xbgw.xbee.ddo_manager.pubsub.pub")
def test_tx_id_exhaustion(pubmock):
    pubmock.reset_mock()

    mgr = DDOEventManager()

    # Fill manager's status callbacks
    # (Get the manager's TxStatusCallbacks object and fill it manually. This is
    # easier than, say, calling the pubsub listener for set_digital_output 255
    # times)
    callbacks = mgr.tx_callbacks
    cb = lambda *a: None
    for _ in xrange(255):
        callbacks.add_callback(cb)

    # Now, get the pubsub listener, send a set_digital_output command, check
    # the return value.
    listener = get_dout_listener(pubmock)

    # Command object
    attrs = {
        'addr': '123456', 'name': "DIO4"
    }
    el = Element("set_digital_output", attrib=attrs)
    el.text = "high"

    rsp_mock = Mock(name="response queue mock")

    listener(element=el, response=rsp_mock)
    assert rsp_mock.put.call_count == 1
    response = rsp_mock.put.call_args[0][0]

    assert_command_error(response, "Too many outstanding transmits")


@patches_socket_and_select
@patch("xbgw.xbee.ddo_manager.pubsub.pub")
def test_empty_poll_result(pubmock):
    pubmock.reset_mock()

    mgr = DDOEventManager()

    # Make manager's poller.poll return an empty list
    mgr.poller.poll.return_value = []

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    attrs = {
        'addr': '123456', 'index': '1'
    }

    el = Element("set_digital_output", attrib=attrs)
    el.text = "low"

    response = Mock()
    listener(element=el, response=response)

    eq_(response.put.call_count, 1)

    # Extract the listener's response
    r = response.put.call_args[0][0]
    assert_command_error(r, errors['txfailed'], "No poll events returned")

    # Check that we never reached the socket.sendto call
    assert not sockmock.return_value.sendto.called


@patches_socket_and_select
@patch("xbgw.xbee.ddo_manager.pubsub.pub")
def test_socket_unavailable_on_poll(pubmock):
    pubmock.reset_mock()

    mgr = DDOEventManager()

    # Make manager's poller.poll return a non-empty list which does not include
    # the manager socket's fileno
    mgr.poller.poll.return_value = [(-1, selectmock.POLLOUT)]

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    attrs = {
        'addr': '123456', 'index': '1'
    }

    el = Element("set_digital_output", attrib=attrs)
    el.text = "low"

    response = Mock()
    listener(element=el, response=response)

    eq_(response.put.call_count, 1)

    # Extract the listener's response
    r = response.put.call_args[0][0]
    errmsg = "Socket not available for write"
    assert_command_error(r, errors['txfailed'], errmsg)

    # Check that we never reached the socket.sendto call
    assert not sockmock.return_value.sendto.called


@patches_socket_and_select
@patch("xbgw.xbee.ddo_manager.pubsub.pub")
def test_socket_error(pubmock):
    pubmock.reset_mock()

    mgr = DDOEventManager()

    # Make the socket appear to be ready for writing
    mgr.poller.poll.return_value = [(mgr.socket.fileno(), selectmock.POLLOUT)]

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    attrs = {
        'addr': '123456', 'index': '1'
    }

    el = Element("set_digital_output", attrib=attrs)
    el.text = "low"

    # Set socket.error as a side effect
    old_se = mgr.socket.sendto.side_effect
    mgr.socket.sendto.side_effect = socket.error(70, "")

    response = Mock()
    listener(element=el, response=response)

    eq_(response.put.call_count, 1)

    # Extract the listener's response
    r = response.put.call_args[0][0]
    # Check that the error message is the return value of os.strerror on the
    # error's errno
    import os
    errmsg = os.strerror(70)
    assert_command_error(r, errors['txfailed'], errmsg)

    # Reset the socket sendto side effect
    mgr.socket.sendto.side_effect = old_se


# Tests for transmission statuses other than 0

@patches_socket_and_select
def do_status_error(pubmock, addr, name, status, message, hint=None):
    pubmock.reset_mock()
    mgr = DDOEventManager()

    # Get the listener from subscribe's last call
    listener = get_dout_listener(pubmock)
    assert listener is not None

    attrs = {
        'addr': addr,
        'name': name
    }

    el = Element("set_digital_output", attrib=attrs)
    el.text = "low"

    response = Mock()
    listener(element=el, response=response)

    eq_(response.put.call_count, 1)
    assert mgr.socket.sendto.called
    # Extract the transaction ID
    sent_addr = mgr.socket.sendto.call_args[0][1]
    tx_id = sent_addr[-1]
    assert response.put.call_args[0][0] is ResponsePending

    response.reset_mock()

    # Normalize the input address, because recvfrom() return values have the
    # normalized addresses.
    recv_addr = normalize_ieee_address(addr)

    mgr.socket.recvfrom.return_value = ("",
                                        (recv_addr, name, 0, tx_id, status))

    # Trigger a read on the socket
    mgr.handle_read()

    eq_(response.put.call_count, 1)
    r = response.put.call_args[0][0]

    assert isinstance(r, DeferredResponse)
    print r.response

    assert_command_error(r.response, message, hint)


def test_status_errors():
    with make_pubmock() as pubmock:
        yield (do_status_error, pubmock, "FEED:CAFE", "D4",
               socket.XBS_STAT_TXFAIL, errors['txfailed'],
               "[00:00:00:00:FE:ED:CA:FE]!")
        yield (do_status_error, pubmock, "abcdef", "D1",
               socket.XBS_STAT_BADCMD, errors['badcmd'], "D1")
        yield (do_status_error, pubmock, "abcdef", "D1",
               socket.XBS_STAT_BADPARAM, errors['badparam'])
        yield (do_status_error, pubmock, "abcdef", "D1", socket.XBS_STAT_ERROR,
               errors['ddo_error'])

        # Unrecognized status code
        yield (do_status_error, pubmock, "abcdef", "D0", 80,
               errors['unexpected'], "Unexpected status: 80")
