# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from xbgw.settings.registry import SettingsRegistry
import json

from mock import patch, mock_open
from nose.tools import eq_, assert_raises
from hamcrest import assert_that, same_instance, is_not, starts_with


registry = None


def setup():
    registry_values = {
        "some": {
            "example": 123
        },
        "data": {
            "here": {
                "setting": [1, 2, 3]
            }
        }
    }

    json_data = json.dumps(registry_values)
    # Patch registry.open, then use load_from_json to populate the
    # settings registry.
    global registry
    registry = SettingsRegistry()
    with patch('xbgw.settings.registry.open',
               mock_open(read_data=json_data), create=True):
        registry.load_from_json("/some/arbitrary/path")


# get_by_binding should traverse the settings tree and return the pre-existing
# object that it finds.
def test_get_by_binding_existing():
    eq_(registry.get_by_binding("some"), {"example": 123})
    eq_(registry.get_by_binding("data"), {"here": {"setting": [1, 2, 3]}})
    eq_(registry.get_by_binding("data.here"), {"setting": [1, 2, 3]})


# get_by_binding should traverse the settings tree and create new dictionaries
# as it descends the tree until it reaches the end of the binding.
def test_get_by_binding_nonexisting():
    # Get the value for 'another.example' and hold onto it
    another_example = registry.get_by_binding("another.example")
    # Check that if we look 'another.example', that we get the same object
    # back.
    assert_that(registry.get_by_binding("another.example"),
                same_instance(another_example))
    # We should have gotten an empty dictionary back.
    eq_(another_example, {})

    # Now, check that a different, non-existing key gets us a different dict,
    # and not the same dict.
    something_else = registry.get_by_binding("something.else")
    # Check that we get the same thing back again...
    assert_that(registry.get_by_binding("something.else"),
                same_instance(something_else))
    # Check that it's not another_example
    assert_that(something_else, is_not(same_instance(another_example)))
    # We should have gotten an empty dictionary back.
    eq_(something_else, {})


# If get_by_binding reaches a non-dict object (e.g. list, int, etc.) and has
# remaining binding chunks to traverse, it should raise a ValueError.
# TODO Create a different exception for this case?
def test_traverse_to_nondict():
    with assert_raises(ValueError) as caught:
        registry.get_by_binding("some.example.here it goes bad")

    assert_that(caught.exception.message,
                starts_with("Cannot traverse subtree of type int"))

    with assert_raises(ValueError) as caught:
        registry.get_by_binding("data.here.setting.here it goes bad")

    assert_that(caught.exception.message,
                starts_with("Cannot traverse subtree of type list"))


# If we have told the registry to stop traversal when we reach a missing key,
# a traversal which reaches a missing key should raise a KeyError
# TODO Create a different exception for this case?
def test_traverse_missing_key():
    registry.set_stop_traversal_on_missing(True)

    with assert_raises(KeyError) as caught:
        registry.get_by_binding("some.other.example")

    eq_(caught.exception.message, "Missing key 'other' in 'some'")
