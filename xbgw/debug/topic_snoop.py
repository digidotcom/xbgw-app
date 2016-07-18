# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import pubsub.pub as pub
import logging

logger = logging.getLogger(__name__)


def snooper(topic=pub.AUTO_TOPIC, *args, **kwargs):
    #pylint: disable=maybe-no-member
    logger.debug("Topic: %s, args: %s, kwargs: %s",
                 topic.getName(), args, kwargs)


class TopicSnoop(object):
    def __init__(self, root):
        pub.subscribe(snooper, root)
