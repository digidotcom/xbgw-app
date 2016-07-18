# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import pubsub.pub


# kwargs is required in order to subscribe, but we do nothing with it.
# pylint: disable=unused-argument
def raise_exc(topic=pubsub.pub.AUTO_TOPIC, **kwargs):
    raise Exception("Listener exception on topic %s" % topic.getName())


class RaiseExceptionOn(object):
    def __init__(self, topic):
        pubsub.pub.subscribe(raise_exc, topic)
