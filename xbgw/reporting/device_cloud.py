# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Define reporting manager for posting data points to Digi Device Cloud
"""

# pylint: disable=import-error
import idigidata  # Provided by XBee Gateway
import pubsub.pub
import logging
import re
import threading
import time
import base64
from collections import deque

from xbgw.settings import Setting, SettingsMixin

logger = logging.getLogger(__name__)


def wrap(fn):
    def wrappedListener(topic=pubsub.pub.AUTO_TOPIC, ident=None,
                        value=None, **kwargs):
        fn(topic, ident=ident, value=value, **kwargs)
    return wrappedListener


def id_to_stream(ident):
    """
    Convert a message identity tuple/list into a DataStream name
    """
    # Ensure that 'ident' is a tuple or list. If ident is a string,
    # say, "abc", the '/'.join call below would result in the string
    # "a/b/c", when we would typically expect just "abc" for the
    # stream name.
    if type(ident) not in (tuple, list):
        logger.warn("Got non-tuple, non-list ID: %s", ident)
        ident = (ident,)

    stream = '/'.join(str(x) for x in ident)

    # Device Cloud Data Stream names must match the following regular
    # expression:
    #   _\-\[\]:a-zA-Z0-9.!/
    # We can use re.subn to escape any non-matching characters in the stream
    # name, to ensure that Device Cloud will accept it.

    # Match any character that doesn't match the regex given above.
    invalid_stream_chars = r'[^_\-\[\]:a-zA-Z0-9.!/]'
    # Replacement for invalid characters.
    stream_escape = '-'

    escaped_stream, replacements = re.subn(invalid_stream_chars,
                                           stream_escape, stream)
    if replacements > 0:
        # At least one character was escaped.
        logger.warn("Escaped %d invalid stream name character(s) in %s",
                    replacements, stream)

    return escaped_stream


def get_type(obj):
    """Return Device Cloud data point type for the given Python object"""
    t = type(obj)
    if t == int or t == bool:
        return "INTEGER"
    elif t == str:
        return "STRING"
    elif t == float:
        return "DOUBLE"

    return "UNKNOWN"


class DeviceCloudReporter(SettingsMixin):
    """Reporting manager which posts data points into Device Cloud

    The Device Cloud reporting manager is agnostic to the actual source of
    the data to be reported.  The MDS (pubsub Message Data Specification)
    for the topics being monitored requires two arguments:

        * ident: A list or tuple of identifying information for the data.
                 An example would be ('sensor1', 'temperature') for temperature
                 data from a particular sensor.
        * value: The current value of the data stream (i.e. the data point
                 value to be reported). This value will be uploaded as
                 a data point of type INTEGER, STRING, DOUBLE, or UNKNOWN
                 depending on the type of `value`. A bool value is treated as
                 an integer.

    Data stream identifiers are prefixed with the pubsub topic name, followed
    by the items in `ident` joined by the character '/'. For example, the
    following code, if added to xbgw_main.py, would populate a data point
    under "example.stream/one/2".

        dc_reporter.start_reporting("example.stream")
        pubsub.pub.sendMessage("example.stream",
                               ident=("one", 2), value="Hello world")

    Available settings:

        * "encode serial": If set to `true`, string values will be converted to
                           base64 encoding when uploaded to Device Cloud
    """

    def __init__(self, settings_registry, settings_binding="device cloud"):
        logger.info("Initializing DeviceCloudReporter")

        settings_list = [
            # Should serial data be base64-encoded before upload?
            Setting(name="encode serial", type=bool, required=False,
                    default_value=False)
        ]

        # Necessary before calling register_settings to initialize state.
        SettingsMixin.__init__(self)
        self.register_settings(settings_registry, settings_binding,
                               settings_list)

        self._topic_registry = {}
        self._work = deque()
        self._work_event = threading.Event()
        self._work_lock = threading.RLock()
        self._last_upload = 0

        self._RETRY_TIME = 5  # seconds to wait upon upload failure
        self._RETRY_COUNT = 3  # Will attempt upload this many times
        # Below value is for DC Free/Developer tier.  Standard tier
        # and above can change this to one second
        self._RATE_LIMIT = 5  # seconds between uploads to DC, per DC throttles
        self._MAX_QUEUE_SIZE = 5000  # items

        # 249 because DC counts the header line, while we only count
        # the DataPoints, leading to an off-by-one disagreement
        self._MAX_PER_UPLOAD = 249  # datapoints per upload

        self._thread = threading.Thread(target=self.__thread_fn)
        self._thread.daemon = True
        self._thread.start()

    def start_reporting(self, topic):
        """Subscribe to pubsub data on the given topic name

        The topic must conform to the MDS documented in the
        DeviceCloudReporter class docstring (ident and value).
        """
        # Grab and hold a reference for just this topic to support
        # unregistration later
        listener = wrap(self.__my_listener)
        self._topic_registry[topic] = listener
        pubsub.pub.subscribe(listener, topic)

    def stop_reporting(self, topic):
        """Unsubscribe from pubsub data on the given topic name

        Will raise KeyError if the topic has not been subscribed to
        (see start_reporting).
        """
        # Removing reference unsubscribes from pubsub (unless owned elsewhere)
        del self._topic_registry[topic]

    def __my_listener(self, topic=pubsub.pub.AUTO_TOPIC, ident=None,
                      value=None, **kwargs):
        # topic is a Topic object. We only care about the topic name.
        # Line confuses pylint; topic re-typed as TopicObj
        topic = topic.getName()  # pylint: disable=maybe-no-member

        logger.debug("%s from %s", topic, ident)
        logger.debug(
            "Topic %s, ident %s, value %s with extra data %s",
            topic, ident, value, kwargs)

        with self._work_lock:
            if len(self._work) >= self._MAX_QUEUE_SIZE:
                self._purge_work()

            self._work.append((topic, ident, value, kwargs, time.time()))
            self._work_event.set()

    def _purge_work(self):
        logger.error("Max queue size exceeded, purging queue")
        self._work.clear()

    def __thread_fn(self):
        while True:
            if len(self._work) == 0:
                self._work_event.wait()

            # Avoid throttling
            next_report = self._last_upload + self._RATE_LIMIT - time.time()
            if next_report > 0:
                logger.debug("Sleeping for %f", next_report)
                time.sleep(next_report)

            if len(self._work) == 0:
                logger.warning("Lost expected data while sleeping.")
            else:
                self._publish_stream()

            with self._work_lock:
                if len(self._work) == 0:
                    # Exhausted the work available
                    self._work_event.clear()

    def _publish_stream(self):
        # Performs an upload of all data, honoring limits
        filename = "DataPoint/upload.csv"
        logger.info("Uploading data to %s", filename)

        body = self._build_body()

        self._upload(body, filename)
        self._last_upload = time.time()

    def _build_body(self):
        lines = ['#TIMESTAMP,DATA,DATATYPE,STREAMID']
        count = 0

        # pylint: disable=maybe-no-member
        while len(self._work) != 0 and count < self._MAX_PER_UPLOAD:
            # deque append and popleft are thread safe
            topic, ident, value, kwargs, timestamp = self._work.popleft()
            stream_id = "{}/{}".format(topic, id_to_stream(ident))
            logger.debug("stream_id: %s", stream_id)

            logger.debug("data: %s", (stream_id, value, kwargs))

            datatype = get_type(value)
            if type(value) == bool:  # Bools are special, report them as ints
                value = int(value)
            elif type(value) == str:
                if self.get_setting("encode serial"):
                    value = base64.b64encode(value)

            lines.append("{},{},{},{}".format(
                int(timestamp * 1000),
                value,
                datatype,
                stream_id))

            count = count + 1

        logger.info("Upload contains %d datapoints", count)
        upload_body = '\n'.join(lines)
        return upload_body

    def _upload(self, body, filename):
        loop_count = 0
        while True:
            success, _, errmsg = idigidata.send_to_idigi(body, filename)

            if success:
                # transmitted successfully
                logger.info("Upload successful")
                break

            if errmsg.startswith("Request throttled."):
                logger.error("Device Cloud throttling, waiting")
                # Wait to try again
                time.sleep(self._RETRY_TIME)
            else:
                logger.warning("Unexpected Device Cloud error, data lost: %s",
                               errmsg)
                break

            if loop_count >= self._RETRY_COUNT:
                logger.error("Exceeded retries, data lost")
                break
            loop_count = loop_count + 1
