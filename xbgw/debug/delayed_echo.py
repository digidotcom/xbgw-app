# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import logging
import time
import threading

import pubsub.pub as pub
from xbgw.command.rci import DeferredResponse, ResponsePending


logger = logging.getLogger(__name__)


def do_echo(element, response):
    logger.debug("Queueing Element: %s", element)
    threading.Thread(target=echo_later, args=(element, response)).start()
    response.put(ResponsePending)


class DelayedEchoCommand(object):
    def __init__(self):
        pub.subscribe(do_echo, "command.echo")


def echo_later(element, response):
    time.sleep(5)
    element = DeferredResponse(element)
    response.put(element)
