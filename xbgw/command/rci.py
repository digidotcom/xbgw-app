# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""Translate and dispatch 'do_command' messages.

Device Cloud provides an ability to send commands in the form of RCI
messages with a 'do_command' element to Python applications running on
XBee Gateway products.  This module intercepts these commands and
makes them available to the system to be handled individually and
independently.

To create an instance of the command processor in the system, simply
call RCICommandProcessor and maintain a reference to the return
value.

Topics
======

Messages are published with the topic naming scheme of the literal
string "command." concatenated with the top-level tag name under
do_command. For example the command "echo" would become the topic
"command.echo".

The MDS for these topics requires two arguments:

| element  | An ElementTree Element, the command element itself  |
| response | A Queue-like object exposing only a 'put' operation |
|          | to provide a channel for responses                  |

Responses will be placed into a sequence of 'response' elements within
the XML response to Device Cloud.  The type of responses is not fixed,
but most types will be transformed to a string and nested within a
'response' element if the response is not provided as an ElementTree
Element.  Therefore, the most flexible way to respond is to craft an
Element, this allows you to have the most control over the structure
and contents returned to Device Cloud.

However, if you craft your own Element, be aware that any tag name
that you provide as your own top level tag will have 'response'
substituted instead.

Worked example
--------------
Consider a command 'echo'.  The XML will have the form

<do_command target="xbgw"><echo>Data to be echoed</echo></do_command>

Listeners will receive an 'element' containing the sub-tree from the
'echo' element down.  Say that the command does a put with an element
representing the following XML:

<echoed>Data to be echoed</echoed>

During processing the 'echoed' tag will be renamed to 'response'.
However, keep in mind that the attributes, if any, will be retained.

The ultimate response will look like:

<do_command target="xbgw">
  <responses command="echo">
    <response>Data to be echoed</response>
  </responses>
</do_command>

Listeners SHOULD respond immediately
----------------------------------

Due to the primarily single-threaded asynchronous design of the
system, and the expectation that responses are populated back to the
processor at publication time, it is best to generate immediate
responses.  This does imply that commands must have other channels for
the reporting of data that would otherwise block and/or cache data for
retrieval when commands are received.

What if I need to report status immediately
-------------------------------------------

If you need to block command processing, use the ResponsePending and
DeferredResponse objects to handshake with the command processor and
allow it to block the system RCI thread rather than application
threads. See the doc-strings of these objects for the expected protocol.

Message Conventions
===================

Naming Commands
---------------
Avoid naming your command in such a way that it may imply synchronous
blocking behavior. For example, a command called 'read_io' would be
likely to trigger an attempt to update the xbee.analog or digital
topics, however it may be construed as performing the update and
responding with the value directly. A better command would be named
something like 'request_io_update'.

Keep command names unambiguous.  Do not be afraid of adding additional
identifying aspects to the command names that you create.  The
behavior of a collision in the command topic namespace will be that
unintentional listeners will attempt to process your command.

Handling of 'element' in listener
---------------------------------
Please do not modify this object.  Any changes may be visible to
other listeners.  Since listener order is not guaranteed, you have no
control over who does and does not see the change.

Minimum Acceptable Response
---------------------------
In order to indicate to the command processor that the command it
published was handled, a response must be put() into the queue handed
to your listener.  The processor will be satisfied with any object,
however not every response will have the same value for the end user.

In the simplest case an empty string will suffice for command
acknowledgment.  However, if your command defers processing, and you
do not intend to wait on that deferred processing to finish, consider
adding a response value indicating the action taken so far. For
example, the response may be the string "Request queued", "Task
scheduled", etc. (If you DO intend to wait for the deferred processing
to finish, use the ResponsePending/DeferredResponse mechanism described
earlier.)

Indicating Error
----------------

If an error occurs during processing, please indicate this by adding
an 'error' element to the top level XML Element of your response.
This element should have an 'id' attribute following the guidelines in
the next section.  Place the error text in a 'desc' element under
that.  This does require that you create an ElementTree Element for
your response rather than a simpler type.  The aim here is to create a
similar error structure to that of the gateway firmware. You may also
use a 'hint' element to provide additional information from the
context in which the error occurred.  Use of the 'hint' element is
strongly encouraged.

A conforming element may be created using the ElementResponse function
from this module.

Error IDs
----------

Each command should implement a consistent catalog of identifiers
unique to all listeners for that command.  All error reports should
use the structure created by the ErrorResponse() method in this module
to report their error ensuring that the unique identifier and
descriptor are present in their response.

In the unusual case where multiple listeners process a single command
and may produce errors independently, special care must be taken to
ensure that errors from each module can be recognized and are unique.

"""
import xml.etree.ElementTree as ET
import Queue
import pubsub.pub as pub
# pylint: disable=import-error
from rci_nonblocking import RciCallback
import logging

logger = logging.getLogger(__name__)

BLOCKING_LIMIT = 30  # Don't let bad commands block forever

errors = {
    'command.unknown': "Command not handled",
    'command.timeout': "Timeout or unexpected exit waiting for response",
}


def RCICommandProcessor():
    logger.info("RCICommandProcessor initialized")
    return RciCallback("xbgw", _handle_rci)


def _handle_rci(body):
    # Wrap in a fake top level element
    body = "".join(["<root>", body, "</root>"])
    root = ET.fromstring(body)

    return_list = []

    for command_element in root:
        resp_xml = process_command(command_element)
        return_list.append(ET.tostring(resp_xml))

    return "".join(return_list)


def process_command(command_element):
    logger.info("Processing command: %s", command_element.tag)

    # TODO: Sanitize the tag before topic generation
    command = "command." + command_element.tag
    responses = PutOnlyQueue()
    pub.sendMessage(command, element=command_element, response=responses)

    # Format responses for sending to client
    resp_xml = ET.Element("responses")
    resp_xml.set("command", command_element.tag)

    # "Friends" with PutOnlyQueue to protect others
    # pylint: disable=protected-access
    if responses._queue.empty():
        response = ErrorResponse("command.unknown", errors,
                                 hint=command_element.tag)
        resp_xml.append(response)

    deferred = 0
    while not responses._queue.empty() or deferred > 0:
        try:
            response = responses._queue.get(timeout=BLOCKING_LIMIT)
        except Queue.Empty:
            # We gave up on any further deferrals, no one likely to respond.
            logger.error("Unexpected exit/timeout while processing %s",
                         command_element.tag)
            break

        if response is ResponsePending:
            logger.debug("Waiting for response")
            # Need to wait for matching DeferredResponse
            deferred += 1
            continue

        if isinstance(response, DeferredResponse):
            logger.debug("Got deferred response")
            # Type checked just above
            # pylint: disable=maybe-no-member
            response = response.response  # Extract "real" response
            deferred -= 1

        # Best effort to deal with "other" data
        if type(response) != ET.Element:
            elem = ET.Element("response")
            elem.text = str(response)
            response = elem

        response.tag = "response"
        resp_xml.append(response)

    if deferred > 0:
        # Exited the loop with outstanding commands, indicate as such to user
        for _ in xrange(deferred):
            response = ErrorResponse(
                "command.timeout", errors)
            resp_xml.append(response)

    return resp_xml


class PutOnlyQueue(object):
    """Hides queue get behavior

    Try to avoid inadvertent modification of queue contents or order

    """

    def __init__(self):
        self._queue = Queue.Queue()

    def put(self, item):
        self._queue.put(item)


# Sentinel to indicate that a command is in process, but incomplete
#
# This is sent by a command handler to indicate to the
# CommandProcessor that it has initiated processing of a command,
# but that the system must wait for the response to be complete.
#
# The CommandProcessor will wait (blocking the thread provided by
# the system) until all responders, including those indicating a
# pending response have been accounted for.
#
# If you defer responding with ResponsePending, your later response
# must be contained in a DeferredResponse object so the system can
# readily distinguish immediate from delayed responses.
ResponsePending = "ResponsePending"


class DeferredResponse(object):
    """Container for responses that were initially delayed

    Used to encapsulate responses to the command processor that it had
    to wait for.  Having a distinct type for these responses allows it
    to identify them specifically in the stream and match them against
    the initial ResponsePending indications.

    """
    def __init__(self, response):
        self.response = response


def ErrorResponse(errcode, errdb, hint=None):
    """Convenience method for error reporting

    This routine allows for consistent creation of error messages
    throughout the system.  It will look up 'errcode' in an error
    catalogue contained in 'errdb'.  Additional context from the
    specific error may be provided by 'hint'.

    'errcode' should be unique to a particular command context.
    'errdb' should implement __getitem__ so that bracket subscripting
    is possible. Python built in list and dict types are acceptable.

    """
    rsp_el = ET.Element("response")
    err_el = ET.SubElement(rsp_el, "error")
    err_el.set("id", errcode)
    desc_el = ET.SubElement(err_el, "desc")
    desc_el.text = errdb[errcode]

    if hint:
        hint_el = ET.SubElement(err_el, "hint")
        hint_el.text = hint
    return rsp_el
