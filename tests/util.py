# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from hamcrest import assert_that, is_not, starts_with
from xml.etree.ElementTree import tostring


class MatchCallable(object):
    """
    Mock-compatible matcher for any callable.
    """
    def __eq__(self, other):
        return callable(other)


def get_pubsub_listener(pubmock, topic):
    """
    Given a mock of pubsub.pub, find the listener that was subscribed to the
    given topic, or None if that topic has not been subscribed to.

    Without this utility function, one would need to do this searching
    manually, or (if one can guarantee subscribe is called only one) use
    the value of call_args.
    """
    for (listener, t), kwargs in pubmock.subscribe.call_args_list:
        if t == topic:
            return listener
    return None


def assert_command_error(response, prefix, hint=None):
    """Verifies structure and basic content of command processor errors"""

    print tostring(response)

    err_el = response.find("error")
    assert_that(err_el, is_not(None))
    desc_el = err_el.find("desc")
    assert_that(desc_el, is_not(None))
    assert_that(desc_el.text, starts_with(prefix))

    if hint:
        hint_el = err_el.find("hint")
        assert_that(hint_el, is_not(None))
        assert_that(hint_el.text, starts_with(hint))
