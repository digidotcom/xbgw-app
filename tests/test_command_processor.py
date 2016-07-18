# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import sys
from mock import Mock, patch, call
import xml.etree.ElementTree as ET
from hamcrest import instance_of, assert_that, equal_to
from hamcrest.library.integration import match_equality

from util import assert_command_error

pubmock = Mock()
# Must be before UUT import
pubpatch = patch("xbgw.command.rci.pub", pubmock)
rcimock = Mock()

sys.modules['rci_nonblocking'] = rcimock
# pylint: disable=import-error
from xbgw.command.rci import (RCICommandProcessor, PutOnlyQueue,
                              ResponsePending, DeferredResponse)
del sys.modules['rci_nonblocking']


def reset_mocks():
    pubmock.reset_mock()
    rcimock.reset_mock()


def setup():
    pubpatch.start()


def teardown():
    pubpatch.stop()


# Context Managers
class captured_queue(object):
    # Capture and make available the "PutOnlyQueue" used by the UUT.
    # Used to put sendMessage side effects when done with them
    # Also has the ability to provide a list of values that will be
    # used to populate the queue
    def __init__(self, values=None):
        self._previous_side_effect = None
        self._queue = None
        self._values = values or []

    def __enter__(self):
        self._previous_side_effect = pubmock.sendMessage.side_effect

        # pylint: disable=unused-argument
        def capture_queue(topic, **kwargs):
            self._queue = kwargs["response"]
            # Populate the values provided for the captured queue
            for value in self._values:
                self._queue.put(value)

        pubmock.sendMessage.side_effect = capture_queue
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pubmock.sendMessage.side_effect = self._previous_side_effect


class captured_callback(object):
    def __init__(self):
        self._cb_list = []
        self._previous_side_effect = None

    def __enter__(self):
        self._previous_side_effect = rcimock.RciCallback.side_effect

        def capture_callback(*args):
            self._cb_list.append(args[1])

        rcimock.RciCallback.side_effect = capture_callback

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        rcimock.RciCallback.side_effect = self._previous_side_effect

    def __call__(self, *args, **kwargs):
        if callable(self._cb_list[0]):
            return self._cb_list[0](*args, **kwargs)
        else:
            raise ValueError("Can't call captured object")

#################### TESTS ####################


# When a single command arrives, send the command to the topic 'command.<cmd>'
def test_command_routing():
    with captured_callback() as cb:
        # UUT keeps the reference alive for CB handling
        # pylint: disable=unused-variable
        uut = RCICommandProcessor()
        cb("<test/>")

    pubmock.sendMessage.assert_called_once_with("command.test",
                element=match_equality(instance_of(ET.Element)),
                response=match_equality(instance_of(PutOnlyQueue)))


# When multiple commands arrive (more than one element at XML level
# below do_command) then each should be dispatched as separate topics
def test_multiple_commands():

    with captured_callback() as cb:
        # UUT keeps the reference alive for CB handling
        # pylint: disable=unused-variable
        uut = RCICommandProcessor()
        cb("<test1/><test2/><test3/><test4/>")

    calls = [
        call("command.test1",
            element=match_equality(instance_of(ET.Element)),
             response=match_equality(instance_of(PutOnlyQueue))),
        call("command.test2",
            element=match_equality(instance_of(ET.Element)),
             response=match_equality(instance_of(PutOnlyQueue))),
        call("command.test3",
            element=match_equality(instance_of(ET.Element)),
             response=match_equality(instance_of(PutOnlyQueue))),
        call("command.test4",
            element=match_equality(instance_of(ET.Element)),
             response=match_equality(instance_of(PutOnlyQueue))),
    ]

    pubmock.sendMessage.assert_has_calls(calls)


# When the sendMessage returns with a single response, Single response
# element should be present; responses -> response
def test_single_response():
    rsp1 = ET.Element("RSP1")
    rsp1.text = "RESPONSE 1"

    with captured_callback() as cb, captured_queue([rsp1]):
        # UUT keeps the reference alive for CB handling
        # pylint: disable=unused-variable
        uut = RCICommandProcessor()
        rtn = cb("<test/>")

    root = ET.fromstring(rtn)
    assert_that(root.tag, equal_to("responses"))
    assert_that(root.get("command"), equal_to("test"))
    assert_that(len(root), equal_to(1))  # Single response
    assert_that(root[0].tag, equal_to("response"))
    assert_that(root[0].text, equal_to(rsp1.text))


# When the sendMessage returns an object, convert into a proper XML
# Element
def do_object_response(rsp1):

    with captured_callback() as cb, captured_queue([rsp1]):
        # UUT keeps the reference alive for CB handling
        # pylint: disable=unused-variable
        uut = RCICommandProcessor()
        rtn = cb("<test/>")

    root = ET.fromstring(rtn)
    assert_that(root.tag, equal_to("responses"))
    assert_that(root.get("command"), equal_to("test"))
    assert_that(len(root), equal_to(1))  # Single response
    assert_that(root[0].tag, equal_to("response"))
    assert_that(root[0].text, equal_to(str(rsp1)))


def test_object_response():
    yield do_object_response, "STRING"
    yield do_object_response, 42
    yield do_object_response, True
    yield do_object_response, [1, 2, "hi"]
    yield do_object_response, {'a': 'hi', 'b': 'there', True: 'huh'}


# When the sendMessage call returns, if the responses is empty report
# unhandled message error to caller
def test_no_response():
    with captured_callback() as cb, captured_queue():
        # UUT keeps the reference alive for CB handling
        # pylint: disable=unused-variable
        uut = RCICommandProcessor()
        rtn = cb("<test/>")

    root = ET.fromstring(rtn)
    assert_that(root.tag, equal_to("responses"))
    assert_that(root.get("command"), equal_to("test"))
    assert_that(len(root), equal_to(1))  # Single response
    assert_command_error(root[0], "Command not handled")


# When a command handler returns a ResponsePending, the processor
# should wait until it has received responses for each left pending
# before proceeding with commands in the command stream
def test_delayed_response():
    # Create the UUT
    with captured_callback() as cb, captured_queue(
            [ResponsePending, DeferredResponse("delayed")]):
        # UUT keeps the reference alive for CB handling
        # pylint: disable=unused-variable
        uut = RCICommandProcessor()
        rtn = cb("<test/>")

    root = ET.fromstring(rtn)
    assert_that(root.tag, equal_to("responses"))
    assert_that(root.get("command"), equal_to("test"))
    assert_that(len(root), equal_to(1))  # Single response
    assert_that(root[0].tag, equal_to("response"))
