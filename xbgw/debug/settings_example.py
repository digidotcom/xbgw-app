# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Simple example of how to use the settings registry

This example also makes use of the RCI command processing
of the application.
"""

import logging
logger = logging.getLogger(__name__)

import pubsub.pub as pub

from xbgw.settings.settings_base import (
    Setting, SettingsMixin, SettingNotFound)


class SettingsExampleCommand(SettingsMixin):
    """
    Example component using both the settings registry and an RCI command

    Use this by adding the following to the main() function of
    xbgw_main.py, before the asyncore.loop() call:

        from xbgw.debug.settings_example import SettingsExampleCommand
        settings_example = SettingsExampleCommand(settings_registry)

    and update xbgw_settings.json with at least the following key-value pair:

        "settings_example": {"a required int": 0}

    You can then send RCI commands to look up setting values, as follows:

        <do_command target="xbgw">
            <settings_example>a string</settings_example>
        </do_command>

    """

    def __init__(self, settings_registry, settings_binding="settings_example"):
        # Component settings are declared as a list of Setting objects.
        settings_list = [
            Setting(name="a string", type=str,
                    required=False, default_value="(default)"),
            Setting(name="a required int", type=int,
                    required=True),
            Setting(name="a list", type=list,
                    required=False, default_value=[1, 2, 3])
        ]
        SettingsMixin.__init__(self)

        # Load settings from the settings registry and make them available via
        # self.get_setting. An exception will be raised if there are any
        # validation errors on the settings.
        self.register_settings(settings_registry, settings_binding,
                               settings_list)

        # Subscribe to "settings_example" RCI command
        pub.subscribe(self.rci_listener, "command.settings_example")

        # Log the value of "a required int" to show settings are working
        logger.debug("'a required int' is set to %d",
                     self.get_setting("a required int"))

    def rci_listener(self, element, response):
        setting_name = element.text

        # Look up setting by name (as given in body of command tag)
        try:
            response.put(str(self.get_setting(setting_name)))
        except SettingNotFound as e:
            response.put("Error: %s" % str(e))
