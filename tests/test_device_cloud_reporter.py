# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from mock import Mock, patch, mock_open
import gc
import sys
import threading
import base64
import time

from util import MatchCallable
from nose.tools import assert_equal

pubmock = Mock()
idigimock = Mock()
# Must be before UUT import
pubpatch = patch("pubsub.pub", pubmock)

sys.modules['idigidata'] = idigimock
from xbgw.reporting.device_cloud import DeviceCloudReporter
del sys.modules['idigidata']


from xbgw.settings.registry import SettingsRegistry


registry = None


def reset_mocks():
    pubmock.reset_mock()
    idigimock.reset_mock()


def setup():
    pubpatch.start()

    # Mock the behavior of 'open' in registry, and use load_from_json to
    # populate the settings registry.
    registry_values = {
        "device cloud": {
            "encode serial": True
        }
    }
    import json
    json_data = json.dumps(registry_values)

    global registry
    registry = SettingsRegistry()

    settings_open_patch = patch('xbgw.settings.registry.open',
                                mock_open(read_data=json_data), create=True)
    with settings_open_patch:
        registry.load_from_json("/some/path")


def teardown():
    pubpatch.stop()


def test_creation():
    reset_mocks()

    DeviceCloudReporter(registry)


def test_start_reporting():
    reset_mocks()

    uut = DeviceCloudReporter(registry)

    uut.start_reporting("example.topic")

    pubmock.subscribe.assert_called_once_with(MatchCallable(), "example.topic")


def test_stop_reporting():
    reset_mocks()
    uut = DeviceCloudReporter(registry)

    listener = []

    def capture_listener(*args):
        listener.append(args[0])

    old_se = pubmock.subscribe.side_effect
    try:
        pubmock.subscribe.side_effect = capture_listener

        uut.start_reporting("example.topic")
        listener_count = len(gc.get_referrers(listener[0]))
        uut.stop_reporting("example.topic")
        assert len(gc.get_referrers(listener[0])) == listener_count - 1
        reset_mocks()
        # After clearing the call objects, there should only be the
        # reference we captured above, no others
        assert len(gc.get_referrers(listener[0])) == 1

    finally:
        pubmock.subscribe.side_effect = old_se


def report_to_device_cloud(timeMock,
                           value, value_repr, data_type,
                           ident=("arg1",),
                           streamid="example.topic/arg1"):
    reset_mocks()
    listener = []
    idigi_send_event = threading.Event()

    def capture_listener(*args):
        listener.append(args[0])

    old_se = pubmock.subscribe.side_effect
    try:
        pubmock.subscribe.side_effect = capture_listener

        uut = DeviceCloudReporter(registry)

        uut.start_reporting("example.topic")

        topicMock = Mock()
        topicMock.getName.return_value = "example.topic"
        # Larger than rate limit to avoid sleep path
        timeMock.return_value = 5.14

        # Return after idigi send has triggered
        def idigi_side_effect(*args):
            idigi_send_event.set()
            return (True, 0, "Success")

        idigimock.send_to_idigi.side_effect = idigi_side_effect

        listener[0](topicMock, ident=ident, value=value)
        idigi_send_event.wait(0.1)
        idigimock.send_to_idigi.side_effect = None

        idigimock.send_to_idigi.assert_called_once_with(
            '#TIMESTAMP,DATA,DATATYPE,STREAMID\n5140,%s,%s,%s' % (
                value_repr, data_type, streamid),
            "DataPoint/upload.csv")

    finally:
        pubmock.subscribe.side_effect = old_se


def test_report_to_device_cloud():
    with patch("time.time") as timeMock:
        # Test type conversions
        yield report_to_device_cloud, timeMock, 500, "500", "INTEGER"
        yield report_to_device_cloud, timeMock, True, "1", "INTEGER"
        yield report_to_device_cloud, timeMock, False, "0", "INTEGER"
        yield report_to_device_cloud, timeMock, 3.14, "3.14", "DOUBLE"
        test_str = "Hello, World!"
        str_send = base64.b64encode(test_str)
        yield (report_to_device_cloud, timeMock, test_str,
               str_send, "STRING")
        yield (report_to_device_cloud, timeMock,
               {"a": "Hello"}, "{'a': 'Hello'}",
               "UNKNOWN")

        ### Test id structure
        # Multiple ID elements
        yield (report_to_device_cloud, timeMock, 500, "500", "INTEGER",
               ("one", "two", "three"),
               "example.topic/one/two/three")
        # Non-sequence IDs
        yield (report_to_device_cloud, timeMock, 500, "500", "INTEGER",
               "arg",
               "example.topic/arg")
        # Non-string, non-sequence
        yield (report_to_device_cloud, timeMock, 500, "500", "INTEGER",
               True,
               "example.topic/True")
        # Escape illegal characters
        yield (report_to_device_cloud, timeMock, 500, "500", "INTEGER",
               "\n\t",
               "example.topic/--")


def test_report_to_device_cloud_no_encoding_serial():
    with patch("time.time") as timeMock:
        # TODO: When the settings system is changed to allow for more managed
        # changes of settings, this test code will need to be changed to
        # reflect that. For now, though, just modify the "encode serial"
        # setting in place.
        settings = registry.get_by_binding("device cloud")
        settings['encode serial'] = False

        yield (report_to_device_cloud, timeMock, "Hello!", "Hello!", "STRING")

@patch("time.sleep")
@patch("time.time")
def test_sleep_between_uploads(timeMock, sleepMock):
    reset_mocks()
    listener = []
    idigi_send_event = threading.Event()

    def capture_listener(*args):
        listener.append(args[0])

    old_se = pubmock.subscribe.side_effect
    try:
        pubmock.subscribe.side_effect = capture_listener

        uut = DeviceCloudReporter(registry)
        # Set specifically so we can ensure they are different
        uut._RATE_LIMIT = 10
        uut._RETRY_TIME = 5

        uut.start_reporting("example.topic")

        topicMock = Mock()
        topicMock.getName.return_value = "example.topic"
        # Less than rate limit to trigger sleep path, should cause a
        # ~3.14 second sleep to occur
        _time = [uut._RATE_LIMIT - 3.14]

        def my_sleep(*args):
            _time[0] = _time[0] + args[0]

        def my_time(*args):
            return _time[0]

        timeMock.side_effect = my_time
        sleepMock.side_effect = my_sleep

        throttled = [False]
        def idigi_side_effect(*args):
            if throttled[0] is False:
                throttled[0] = True
                return (False, 3, "Request throttled. For test")
            else:
                idigi_send_event.set()
                return (True, 0, "Success")

        idigimock.send_to_idigi.side_effect = idigi_side_effect

        listener[0](topicMock, ident=("ident1",), value="hello")

        idigi_send_event.wait(10)
        idigimock.send_to_idigi.side_effect = None

        assert_equal(sleepMock.call_count, 2)
        # First call, positional argument 0, sleep based on initial last_upload
        assert abs(sleepMock.mock_calls[0][1][0] - 3.14) < 0.001
        assert_equal(idigimock.send_to_idigi.call_count, 2)

        # Second call, wait due to throttling
        assert_equal(sleepMock.mock_calls[1][1][0], uut._RETRY_TIME)

    finally:
        pubmock.subscribe.side_effect = old_se


@patch("threading.Thread")
def test_queue_overflow(threadMock):
    reset_mocks()
    listener = []

    def capture_listener(*args):
        listener.append(args[0])

    old_se = pubmock.subscribe.side_effect
    try:
        pubmock.subscribe.side_effect = capture_listener

        uut = DeviceCloudReporter(registry)
        uut._MAX_QUEUE_SIZE = 10
        uut.start_reporting("example.topic")
        topicMock = Mock()
        topicMock.getName.return_value = "example.topic"

        for item in xrange(uut._MAX_QUEUE_SIZE):
            listener[0](topicMock, ident=("dummy",), value="hello")

        # Verify that max queue size is reached exactly
        assert_equal(len(uut._work), uut._MAX_QUEUE_SIZE)

        listener[0](topicMock, ident=("dummy,"), value="hello")
        # Queue should have been purged and the single item just
        # inserted should be the only thing present
        assert_equal(len(uut._work), 1)

    finally:
        pubmock.subscribe.side_effect = old_se


