# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Define XBee socket event manager for DDO (AT command) operations
"""

import xbee  # pylint: disable=unused-import,import-error
import socket
import asyncore
import logging
import select
import struct
from xml.etree.ElementTree import Element

# pylint, virtualenv, and distutils do not play nicely together
# pylint: disable=import-error,no-name-in-module
from distutils.util import strtobool

import pubsub.pub
from xbgw.command.rci import ResponsePending, DeferredResponse, ErrorResponse
from xbgw.xbee import utils

logger = logging.getLogger(__name__)

# pylint: disable=no-member
TX_STATUSES = {
    socket.XBS_STAT_OK: "Success",
    socket.XBS_STAT_ERROR: "Error",
    socket.XBS_STAT_BADCMD: "Invalid DDO command name",
    socket.XBS_STAT_BADPARAM: "Invalid DDO command value",
    socket.XBS_STAT_TXFAIL: "Transmit failure"
}

errors = {
    "address": "Invalid address",
    "badoutput": "Invalid digital output value",
    "invalidattr": "Attribute value is incorrect",
    "missingattr": "Missing required command attribute",
    "toomanyattrs": "Too many attributes were given",
    # XBee FW only presents statuses 0-4 (see TX_STATUSES) when performing DDO
    # commands. All we can say here is 'error'.
    "ddo_error": "DDO command error",
    "badcmd": "Invalid DDO command name",
    "badparam": "Invalid DDO command value",
    "txfailed": "Transmit operation failed",
    "txfull": "Too many outstanding transmits",
    "unexpected": "Unexpected/unclassified error",
}

BAD_NAME_MAP = {
    'ASSOC': 5, 'RTS': 6, 'CTS': 7,
    'DTR': 8, 'SLEEP_RQ': 8, 'ON': 9, 'SLEEP': 9,
    'PWM0': 10, 'RSSI': 10, 'P0': 10,
    'PWM': 11, 'P1': 11, 'P2': 12
}

PIN_MAP = {}
INVERSE_PIN_MAP = {}

for i in xrange(13):
    INVERSE_PIN_MAP[i] = INVERSE_PIN_MAP.get(i, [])

    # Add DIOx mappings to PIN_MAP
    PIN_MAP['DIO%i' % i] = i
    INVERSE_PIN_MAP[i].append('DIO%i' % i)

    # Add Dx mappings to PIN_MAP
    if i < 10:
        PIN_MAP['D%i' % i] = i
        INVERSE_PIN_MAP[i].append('D%i' % i)

    # Add ADx mappings to bad name map
    if i < 7:
        BAD_NAME_MAP['AD%i' % i] = i


def _parse_digital_value(value):
    """
    Returns the text value for a digital-out command into its corresponding pin
    setting value: 4 for low, 5 for high. Returns 0 if the value is invalid.
    """
    value_l = value.lower()
    if value_l == "low":
        return 4
    elif value_l == "high":
        return 5

    try:
        # Add 4 to the parsed value, so that "low"/falsy values correspond to
        # '4' (digital out, low) and "high"/truthy values correspond to 5
        # (digital out, high)
        return strtobool(value) + 4
    except ValueError:
        return 0


def _pin_index_to_setting(pin):
    """Returns the setting name for the given IO pin index."""
    if pin < 10:
        return 'D%d' % pin
    else:
        return 'P%d' % (pin - 10)


class SocketUnavailable(Exception):
    """
    Exception raised internally when polling the socket reveals that the
    socket is not writable.
    """
    pass


class DDOEventManager(asyncore.dispatcher):
    """XBee socket event manager in charge of DDO operations

    XBee Gateway provides Python socket APIs which allow the user
    to perform asynchronous DDO (Digi Device Object) operations.
    DDO is used to implement remote XBee AT commands.

    DDOEventManager is an asyncore dispatcher object which wraps
    one of these DDO sockets, and subscribes to the application's
    RCI command processing to implement the "set_digital_output"
    command.
    """

    DIGITAL_OUT_COMMAND = "command.set_digital_output"

    def __init__(self):
        asyncore.dispatcher.__init__(self)
        logger.info("Initializing DDOEventManager")

        # XBee values come from XBee Gateway implementation
        # This will raise an exception if the platform doesn't support XBee
        # sockets, or DDO sockets. We will not catch and log this error,
        # because that is a major issue which should be brought to the user's
        # attention.
        # pylint: disable=no-member
        sock = socket.socket(socket.AF_XBEE,
                             socket.SOCK_DGRAM,
                             socket.XBS_PROT_DDO)
        self.set_socket(sock)

        # Register the socket with a poll object so we know when we can write
        # to it.
        self.poller = select.poll()
        self.poller.register(sock.fileno(), select.POLLOUT)

        pubsub.pub.subscribe(self.digital_out_listener,
                             self.DIGITAL_OUT_COMMAND)

        self.tx_callbacks = utils.TxStatusCallbacks()

    def handle_connect_event(self):
        self.handle_connect()
        self.connected = True

    def writable(self):
        # We don't want to rely on asyncore's selecting and iterating to write
        # out to the DDO socket.
        return False

    def handle_write_event(self):
        # Override to avoid some attempts to deal with connecting and accepting
        # logic, which is inappropriate for DDO sockets.
        self.handle_write()

    def handle_write(self):
        # DO nothing on attempted write.
        logger.warn("handle_write called on DDOEventManager")

    def handle_error(self):
        _, t, v, tbinfo = asyncore.compact_traceback()
        logger.error("Uncaught exception: %s (%s:%s %s)",
                     repr(self), t, v, tbinfo)
        # TODO: Call self.handle_close() if it's a really bad error?

    def handle_read(self):
        data, addr = self.socket.recvfrom(255)
        logger.debug("Received frame from %s", addr)

        self.handle_tx_status(data, addr)

    def handle_tx_status(self, data, addr):
        # Get the transmission ID
        tx_id = addr[3]

        try:
            callback = self.tx_callbacks.get_callback(tx_id)
        except IndexError, e:
            # Invalid transmission ID.
            logger.error("Problem handling TX status: %s", e.message)
            return

        if not callback:
            # No callback for this transmission ID.
            logger.info("No callback registered for transmission ID %d", tx_id)
            return

        # Remove status callback.
        self.tx_callbacks.remove_callback(tx_id)

        if callable(callback):
            # Call the callback.
            callback(data, addr)
        else:
            # Callback is not callable.
            logger.info("Non-callable callback for TX ID %d", tx_id)

    def digital_out_listener(self, element, response):
        # Get the values of the attributes and the text content
        addr = element.get("addr", None)
        index = element.get("index", None)
        name = element.get("name", None)
        value = element.text or ""
        # Remove whitespace from command body
        value = value.strip()

        # Check the attributes

        if not addr:
            # Cannot set DIO value without a destination address.
            errmsg = "No destination XBee address (attribute 'addr') given."
            response.put(ErrorResponse("missingattr", errors, hint=errmsg))
            return

        try:
            addr = utils.normalize_ieee_address(addr)
        except (ValueError, TypeError) as e:
            # Address is invalid. (TypeError is raised if addr is not a number
            # or string.)
            response.put(ErrorResponse("address", errors, e.message))
            return
        except Exception, e:
            # Unexpected error parsing address.
            response.put(ErrorResponse("unexpected", errors,
                                       "Problem parsing address: %s" % str(e)))
            return

        if not index and not name:
            # Need to specify either index or name. Neither was given.
            errmsg = ("No digital output pin number (attribute 'index') or "
                      "name alias (attribute 'name') given")
            response.put(ErrorResponse("missingattr", errors, hint=errmsg))
            return

        if index is not None and name is not None:
            # Got both an index and a name. This is considered an error.
            errmsg = "Must specify only an index or a name, not both."
            response.put(ErrorResponse("toomanyattrs", errors, hint=errmsg))
            return

        if index:
            # Command specified a pin index. Parse that index out.
            try:
                index = int(index)
            except ValueError:
                # We check later that 'index' is in the valid range, so set it
                # to an invalid value here.
                index = -1

            if index < 0 or index > 12:
                # Index out of range, or did not represent a valid integer.
                errmsg = ("Pin number ('index') must be an integer between "
                          "0 and 12")
                response.put(ErrorResponse("invalidattr", errors, hint=errmsg))
                return
        elif name in BAD_NAME_MAP:
            # The name given is one which we consider to be invalid.
            # (E.g. PWM0 instead of DIO10, AD5 instead of DIO5, etc.)
            pin = BAD_NAME_MAP[name]
            if pin in INVERSE_PIN_MAP:
                # Use values in INVERSE_PIN_MAP to give suggestions of what
                # name to use instead.
                suggestions = ' or '.join(INVERSE_PIN_MAP[pin])
                hint = "Bad digital output name; use %s instead."
                hint %= suggestions
            else:
                # We have no suggestions of what to use instead.
                hint = name

            response.put(ErrorResponse("invalidattr", errors, hint))
            return
        elif name in PIN_MAP:
            # We consider this name to be valid, so look up its corresponding
            # 'index' number.
            index = PIN_MAP[name]
        else:
            # The name isn't recognized at all, as either valid or invalid.
            error = "Unrecognized digital output name: '%s'" % name
            response.put(ErrorResponse("invalidattr", errors, hint=error))
            return

        if index == 9:
            # Cannot set pin 9 to digital on ZB products. Currently this is all
            # we support, so refuse this command.
            # TODO: Make this a configuration option.
            errmsg = "DIO9 cannot be configured for digital"
            response.put(ErrorResponse("invalidattr", errors, hint=errmsg))
            return

        # Change the index into the corresponding DDO command name.
        setting = _pin_index_to_setting(index)

        parsed_value = _parse_digital_value(value)
        if not parsed_value:
            # Could not parse the command value.
            response.put(ErrorResponse("badoutput", errors, hint=str(value)))
            return

        # Register a callback for this command's transmission status.
        try:
            # The lambda makes 'response' from this context available to the
            # callback, without nesting status_callback within this function.
            l = lambda data, addr: status_callback(data, addr, response)
            txid = self.tx_callbacks.add_callback(l)
        except utils.CallbacksFull:
            # No more callback slots are available.
            response.put(ErrorResponse("txfull", errors))
            return

        dest_addr = (addr, setting, socket.XBS_OPT_DDO_APPLY, txid)
        # Pack the value into a bytestring.
        dest_value = struct.pack('!I', parsed_value)

        try:
            logger.debug("Attempting to set %s=%d on %s",
                         setting, parsed_value, addr)
            self.attempt_send(dest_value, dest_addr)

            # Can't respond fully until we get the TX status.
            response.put(ResponsePending)
        except (SocketUnavailable, socket.error) as e:
            # Remove no longer interesting status callback.
            self.tx_callbacks.remove_callback(txid)

            errmsg = e.message
            if not errmsg:
                # e.message is empty - try to determine the error
                try:
                    import os
                    errmsg = os.strerror(e.errno)
                except ValueError:
                    # According to os.strerror documentation, this means that
                    # the platform returns NULL when given an unknown error
                    # number.
                    errmsg = str(e)

            logger.info("Problem sending DDO command: %s", errmsg)
            response.put(ErrorResponse("txfailed", errors, hint=errmsg))
        except Exception, e:
            # Remove no longer interesting status callback
            self.tx_callbacks.remove_callback(txid)

            logger.error("Exception caught on digital attempt_send: %s", e)
            response.put(ErrorResponse("txfailed", errors, hint=str(e)))

    def attempt_send(self, payload, address):
        # Poll the socket, return info immediately.
        fds = self.poller.poll(0)

        if not fds:
            raise SocketUnavailable("No poll events returned")
        else:
            sockfd = self.socket.fileno()
            for fd, event in fds:
                if fd == sockfd and event == select.POLLOUT:
                    # Socket is available for writing.
                    self.socket.sendto(payload, address)
                    break
            else:
                # This socket was not found to be available.
                raise SocketUnavailable("Socket not available for write")


# pylint: disable=no-member
def status_callback(data, addr, response):
    resp = Element("response")

    address, sent_cmd, _, _, status = addr[0:5]

    if status not in TX_STATUSES:
        logger.warning("Unexpected status: %s", status)
        resp = ErrorResponse('unexpected', errors,
                             hint="Unexpected status: %s" % status)
        response.put(DeferredResponse(resp))
        return

    if status == socket.XBS_STAT_OK:
        logger.info("DDO command succeeded")
        resp.text = data or ""
    elif status == socket.XBS_STAT_TXFAIL:
        logger.warning("Failed TX: %d", status)
        resp = ErrorResponse('txfailed', errors, hint=address)
    elif status == socket.XBS_STAT_BADCMD:
        logger.warning("Failed command - bad command (%s)", sent_cmd)
        resp = ErrorResponse('badcmd', errors, hint=sent_cmd)
    elif status == socket.XBS_STAT_BADPARAM:
        logger.warning("Failed command - bad parameter")
        resp = ErrorResponse('badparam', errors)
    elif status == socket.XBS_STAT_ERROR:
        logger.warning("Failed command - XBS_STAT_ERROR")
        resp = ErrorResponse('ddo_error', errors)

    response.put(DeferredResponse(resp))
