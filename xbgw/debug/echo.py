# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import pubsub.pub as pub
import logging

logger = logging.getLogger(__name__)


def do_echo(element, response):
    logger.debug("Element: %s", element)
    response.put(element)


class EchoCommand(object):
    def __init__(self):
        pub.subscribe(do_echo, "command.echo")
