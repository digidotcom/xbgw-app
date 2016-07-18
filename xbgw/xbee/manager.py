# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Define XBee socket event manager for serial and I/O operations
"""

import xbee  # pylint: disable=unused-import,import-error
import socket
import asyncore
import logging
import select
import base64
import struct
from xml.etree.ElementTree import Element

import pubsub.pub
import xbgw.xbee.io_sample as io_sample
from xbgw.command.rci import ResponsePending, DeferredResponse, ErrorResponse
from xbgw.xbee import utils
from xbgw.settings import Setting, SettingsMixin

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = 0xe8
DIGI_PROFILE = 0xc105
SERIAL_CLUSTER = 0x11
# X-API ZigBee transmit status frame
TX_STATUS_CLUSTER_ZB = 0x8b
IO_CLUSTER = 0x92

TX_STATUSES = {
    0x00: "Success",
    0x01: "MAC ACK Failure",
    0x02: "CCA Failure",
    0x15: "Invalid destination endpoint",
    0x21: "Network ACK Failure",
    0x22: "Not joined to network",
    0x23: "Self addressed",
    0x24: "Address not found",
    0x25: "Route not found",
    0x26: "Broadcast source failed to hear a neighbor relay the message",
    0x2b: "Invalid binding table index",
    0x2c: "Resource error; lack of free buffers, timers, etc",
    0x2d: "Attempted broadcast with APS transmission",
    0x2e: "Attempted unicast with APS transmission, but EE=0",
    0x32: "Resource error; lack of free buffers, times, etc",
    0x74: "Data payload too large",
}

errors = {
    "address": "Invalid address",
    "encoding": "Unrecognized encoding",
    "base64": "Unable to decode as base64",
    "invalidattr": "Attribute value is incorrect",
    "missingattr": "Missing required command attribute",
    "toomanyattrs": "Too many attributes were given",
    "txfailed": "Transmit operation failed",
    "txfull": "Too many outstanding transmits",
    "txstatus": "TX Status delivery failure",
    "unexpected": "Unexpected/unclassified error",
}


class SocketUnavailable(Exception):
    """
    Exception raised internally when polling the socket reveals that the
    socket is not writable.
    """
    pass


class XBeeEventManager(asyncore.dispatcher, SettingsMixin):
    """XBee socket event manager in charge of serial and I/O operations

    XBee Gateway provides Python socket APIs which allow the user to
    send serial data over the network (using the Explicit Transmit/Receive
    capability of XBees), and to receive messages such as I/O samples,
    in an asynchronous manner.

    XBeeEventManager is an asyncore dispatcher object which wraps
    one of these XBee sockets, publishes information about incoming
    digital and analog readings (to be reported to Device Cloud),
    and subscribes to the application's RCI command processing to
    implement the "send_serial" command.
    """

    data_topics = ["xbee.analog", "xbee.digitalIn", "xbee.serialIn"]
    SEND_SERIAL_COMMAND = "command.send_serial"

    def __init__(self, settings_registry, settings_binding="xbee_manager"):
        asyncore.dispatcher.__init__(self)
        logger.info("Initializing XBeeEventManager")

        settings_list = [
            # Don't publish repeated analog readings
            Setting(name="filter_analog_duplicates", type=bool,
                    required=False, default_value=True),
            # Smallest analog difference to report
            Setting(name="minimum_analog_change", type=int,
                    required=False, default_value=1),
            # Don't publish repeated digital readings
            Setting(name="filter_digital_duplicates", type=bool,
                    required=False, default_value=True),
        ]

        # Necessary before calling register_settings to initialize state.
        SettingsMixin.__init__(self)
        self.register_settings(settings_registry, settings_binding,
                               settings_list)

        # XBee values come from XBee Gateway implementation
        # pylint: disable=no-member
        sock = socket.socket(socket.AF_XBEE,
                             socket.SOCK_DGRAM,
                             socket.XBS_PROT_TRANSPORT)
        try:
            sock.bind(('', DEFAULT_ENDPOINT, 0, 0))
        except socket.error, err:
            from errno import EOPNOTSUPP, EALREADY
            if err.args[0] in (EOPNOTSUPP, EALREADY):
                # Socket is already in use on the system.
                logger.error("XBeeEventManager - XBee socket already in use")
                return
        self.set_socket(sock)

        # Enable transmission status reports on calls to recvfrom()
        sock.setsockopt(socket.XBS_SOL_EP, socket.XBS_SO_EP_TX_STATUS, 1)

        # Register the socket with a poll object so we know when we can write
        # to it.
        self.poller = select.poll()
        self.poller.register(sock.fileno(), select.POLLOUT)

        pubsub.pub.subscribe(self.send_serial_listener,
                             self.SEND_SERIAL_COMMAND)

        # Track callbacks for receipt of transmit status frames.
        # NOTE: An improved implementation of this class might maintain a
        # mapping from transmit ID to (response_queue, callback) tuple, where,
        # if a callback is provided, its return value will be put on the
        # response queue, or else a generic status indication response will be
        # put on the queue.
        self.tx_callbacks = utils.TxStatusCallbacks()

        # Track previously reported values for I/O Data filtering
        self._last_report = {}

    def handle_connect_event(self):
        self.handle_connect()
        self.connected = True

    def handle_serial(self, addr, data):
        logger.debug("Received serial data from %s: %s", addr, data)
        pubsub.pub.sendMessage("xbee.serialIn",
                               ident=(addr[0],), value=data)

    def handle_io(self, addr, data):
        iodata = io_sample.parse_is(data)
        for key, value in iodata.iteritems():
            logger.debug("Processing IO sample from pin %s", key)
            if key.startswith("AD"):
                self._process_analog(addr, key, value)
            elif key.startswith("DIO"):
                self._process_digital(addr, key, value)

    def _process_analog(self, addr, key, value):
        logger.debug("Analog data: %d", value)

        filtered = self.get_setting("filter_analog_duplicates")
        filter_key = "{} - {}".format(addr[0], key)
        difference = self.get_setting("minimum_analog_change")

        if filtered:
            old_value = self._last_report.get(filter_key)
            if old_value is not None and abs(value - old_value) < difference:
                logger.debug("Dropping %s", filter_key)
                return

        pubsub.pub.sendMessage("xbee.analog",
                               ident=(addr[0], key), value=value)
        self._last_report[filter_key] = value

    def _process_digital(self, addr, key, value):
        logger.debug("Digital reading: %d", value)

        filtered = self.get_setting("filter_digital_duplicates")
        filter_key = "{} - {}".format(addr[0], key)

        if filtered:
            old_value = self._last_report.get(filter_key)
            if old_value == value:
                # No need to continue and publish what has already
                # been reported
                logger.debug("Dropping %s", filter_key)
                return

        pubsub.pub.sendMessage("xbee.digitalIn",
                               ident=(addr[0], key), value=value)
        self._last_report[filter_key] = value

    def handle_tx_status(self, addr, data):
        tx_id = addr[5]

        # Log interesting data
        items = struct.unpack("2BH3B", data)
        _, _, _, retry, delivery_status, discovery_status = items
        logger.debug("TX Retries: %d", retry)
        logger.debug("Delivery status: %d", delivery_status)
        logger.debug("Discovery status: %d", discovery_status)

        try:
            callback = self.tx_callbacks.get_callback(tx_id)
        except IndexError, e:
            # Invalid transmission ID. This is a truly exceptional case.
            logger.error("Problem handing TX status: %s", e.message)
            return

        if not callback:
            # No callback for this transmission ID.
            logger.info("No callback registered for transmission ID %d", tx_id)
            return

        # Remove status callback.
        self.tx_callbacks.remove_callback(tx_id)

        if callable(callback):
            # Call the callback.
            callback(addr, retry, delivery_status, discovery_status)
        else:
            # Callback is not callable.
            logger.info("Non-callable callback registered for TX ID %d", tx_id)

    def handle_read(self):
        data, addr = self.socket.recvfrom(255)

        addr = utils.Address(*addr)  # pylint: disable=star-args
        logger.debug("Received frame from %s", addr)

        if addr[2] != DIGI_PROFILE:
            logger.info("Received data for profile %x, discarding", addr[2])
            return

        if addr[3] == SERIAL_CLUSTER:
            self.handle_serial(addr, data)
        elif addr[3] == IO_CLUSTER:
            self.handle_io(addr, data)
        elif addr[3] == TX_STATUS_CLUSTER_ZB:
            self.handle_tx_status(addr, data)
        else:
            logger.info("Unhandled XBee packet from %s", addr)
            logger.debug("Unhandled packet payload: %s", repr(data))

    def send_serial_listener(self, element, response):
        addr = element.get("addr")
        encoding = element.get("encoding", default="base64")
        msg = element.text

        if not addr:
            # Cannot send frame without having a destination address.
            response.put(ErrorResponse("missingattr", errors,
                                       ("No destination XBee address "
                                        "(attribute 'addr') given.")))
            return

        # Validate address
        try:
            if addr == "broadcast":
                # Alias broadcast for ease of memory
                addr = '[00:00:00:00:00:00:FF:FF]!'
            addr = utils.normalize_ieee_address(addr)
        except ValueError, e:
            # Address is invalid.
            response.put(ErrorResponse("address", errors, e.message))
            return
        except Exception, e:
            # TypeError if addr is not a number or string. Any other exception
            # would be currently unexpected.
            response.put(ErrorResponse("unexpected", errors,
                                       "Problem parsing address: %s" % str(e)))
            return

        # Encode/decode for transmit
        if encoding == "base64":
            try:
                msg = base64.b64decode(msg)
            except TypeError:
                response.put(ErrorResponse("base64", errors))
                return
        elif encoding == "utf-8":
            # ElementTree has turned this into a Python UnicodeString
            # by the time we get it here. We need to reverse its
            # helpfulness.
            msg = msg.encode('utf-8')
        else:
            # ERROR: encoding not recognized
            response.put(ErrorResponse("encoding", errors, hint=encoding))
            logger.error("Unrecognized encoding: %s", encoding)
            return

        try:
            # The lambda makes 'response' from this context available
            # to the CB without nesting the callback, this method is
            # long enough is it is.
            l = lambda a, b, c, d, e=response: status_callback(a, b, c, d, e)
            txid = self.tx_callbacks.add_callback(l)
        except utils.CallbacksFull:
            response.put(ErrorResponse("txfull", errors))
            return

        dest_addr = utils.Address(addr, DEFAULT_ENDPOINT, DIGI_PROFILE,
                                  SERIAL_CLUSTER, 0, txid)
        try:
            logger.debug("Sending %d bytes of serial data to %s",
                         len(msg), dest_addr)
            self.attempt_send(msg, dest_addr.to_tuple())
        except (SocketUnavailable, socket.error) as e:
            # Remove no longer interesting status
            self.tx_callbacks.remove_callback(txid)

            errmsg = e.message
            if not errmsg:
                # i.e. message is empty
                try:
                    import os
                    errmsg = os.strerror(e.errno)
                except ValueError:
                    # According to os.strerror documentation, this means that
                    # the platform returns NULL when given an unknown error
                    # number.
                    errmsg = str(e)

            logger.info("Problem sending serial data: %s", errmsg)
            response.put(ErrorResponse("txfailed", errors, errmsg))
            return
        except Exception, e:
            # Remove no longer interesting status
            self.tx_callbacks.remove_callback(txid)

            logger.error("Exception caught around serial attempt_send: %s", e)
            response.put(ErrorResponse("txfailed", errors, str(e)))
            return

        # Can't respond fully until TX Status returns
        response.put(ResponsePending)

    def writable(self):
        # We don't want to rely on asyncore's selecting and iterating to write
        # out to the XBee socket.
        return False

    def handle_write_event(self):
        # Override to avoid some attempts to deal with connecting and
        # accepting logic, which is inappropriate for XBee sockets
        self.handle_write()

    def handle_write(self):
        # Do nothing on attempted write.
        logger.warn("handle_write called on XBeeEventManager")

    def handle_error(self):
        _, t, v, tbinfo = asyncore.compact_traceback()
        logger.error("Uncaught exception: %s (%s:%s %s)",
                     repr(self), t, v, tbinfo)
        # TODO: Call self.handle_close() if it's a really bad error?

    def attempt_send(self, payload, address):
        # Poll the socket, return info immediately
        fds = self.poller.poll(0)
        if not fds:
            raise SocketUnavailable("No poll events returned")
        else:
            sockfd = self.socket.fileno()
            for fd, event in fds:
                if fd == sockfd and event == select.POLLOUT:
                    self.socket.sendto(payload, address)
                    break
            else:
                # This socket was available, but not for writing.
                raise SocketUnavailable("Socket not available for write")


# pylint: disable=unused-argument
# Callback executed when transmission status information comes in.
def status_callback(addr, retries, delivery_status, discovery_status,
                    response):
    # Generate response to command processor
    resp = Element("response")

    if delivery_status != 0:
        # Report error
        errmsg = "0x%02x: " % delivery_status
        if delivery_status in TX_STATUSES:
            errmsg += TX_STATUSES[delivery_status]
        else:
            errmsg += "Unknown"

        logger.warning("Failed TX: %s", errmsg)
        resp = ErrorResponse('txstatus', errors, hint=errmsg)
    else:
        resp.text = ""

    response.put(DeferredResponse(resp))
