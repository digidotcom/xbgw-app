# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Unit tests of the SettingsMixin class.

These tests will be done by creating a class for testing, which subclasses from
SettingsMixin (i.e. uses it as a mixin).
"""
from xbgw.settings.settings_base import (Setting, SettingsMixin, BadSettings,
                                         SettingNotFound)
from xbgw.settings.registry import SettingsRegistry
from nose.tools import eq_, assert_raises
from mock import patch, mock_open
from hamcrest import assert_that, contains_string


jsondata = '{"example": {"encode serial": true}}'
openpatch = patch('xbgw.settings.registry.open',
                  mock_open(read_data=jsondata), create=True)
del jsondata


class UUTClass(SettingsMixin):
    def __init__(self, registry, binding, settings):
        SettingsMixin.__init__(self)
        self.register_settings(registry, binding, settings)


def get_registry():
    with openpatch:
        registry = SettingsRegistry()
        registry.load_from_json("/some/path")
        return registry


def test_creation():
    registry = get_registry()

    setting_list = [
        Setting(name="encode serial", type=bool, required=True)
    ]
    uut = UUTClass(registry, "example", setting_list)


def test_creation_missing_setting_raises():
    registry = get_registry()

    setting_list = [
        Setting(name="other setting", type=str, required=True)
    ]

    with assert_raises(BadSettings):
        UUTClass(registry, "example", setting_list)


def test_creation_rejected_setting_raises():
    registry = get_registry()

    # Verify 'encode serial' setting to be falsy.
    setting_list = [
        Setting(name="encode serial", type=bool, required=True,
                verify_function=lambda i: not i)
    ]

    with assert_raises(BadSettings) as caught:
        UUTClass(registry, "example", setting_list)

    assert_that(caught.exception.message,
                contains_string("failed verification function"))


def test_get_setting_works():
    registry = get_registry()

    setting_list = [
        Setting(name="encode serial", type=bool, required=True)
    ]

    uut = UUTClass(registry, "example", setting_list)

    eq_(uut.get_setting("encode serial"), True)


def test_get_setting_raises_on_bad_name():
    registry = get_registry()

    setting_list = [
        Setting(name="encode serial", type=bool, required=True)
    ]

    uut = UUTClass(registry, "example", setting_list)

    with assert_raises(SettingNotFound):
        uut.get_setting("some other setting")
