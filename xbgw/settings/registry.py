# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Define settings registry abstraction for application configuration
"""

import json


# Specifies the character (or character sequence) used to delimit sections of a
# settings "binding", e.g. "reporting.device cloud".
BINDING_JOINER = '.'


def _binding_to_tuple(binding):
    """
    Turn a binding string into a tuple of its pieces.

    This function takes in a binding string and returns a tuple of the
    non-empty constituent pieces of the binding.

    >>> _binding_to_tuple("abc.def...g h i. ")
    ('abc', 'def', 'g h i', ' ')
    >>> _binding_to_tuple("...")
    ()
    """
    return tuple([s for s in binding.split(BINDING_JOINER) if len(s)])


class SettingsRegistry(object):

    """
    Encapsulation of settings for the application.

    Bindings
    ========

    Settings are held in an internal dictionary, i.e. a tree. To access a given
    subsection of this settings tree, call `get_by_binding` and pass in a
    'binding' for the section.

    A 'binding' is a string representing the lookup path for a given location
    in the settings tree. Examples include the following:
        - settings.general
        - device cloud
        - xbee.serial settings.config1

    A binding is used to perform lookups in the settings tree by first
    splitting the binding by period (the '.' character) and traversing the tree
    step-by-step, reading the split binding left-to-right and using each
    substring as a key to be accessed. For example, if the settings tree looked
    like this (conceptually):

        settings:
            general:
                setting1 = 1
                setting2 = 4
        xbee:
            serial settings:
                config1:
                    foo = foo
                    bar = baz
        device cloud:
            encode serial = true

    then `get_by_binding("settings.general")` will return the value of
    tree['settings']['general'], which in this case is the dictionary holding
    keys "setting1" and "setting2".

    """

    def __init__(self):
        self.__settings_registry = {}
        self.__stop_traversal_on_missing = False

    def set_stop_traversal_on_missing(self, value=True):
        """
        Set whether an error is raised when a missing key is accessed.

        If the "stop traversal on missing" attribute of this registry is set to
        False (its default value), then when traversing the settings tree to
        look up a given binding, an empty dictionary will be inserted for any
        missing key. If this attribute is set to True, a KeyError will be
        raised if a missing key is reached.

        >>> reg = SettingsRegistry()
        >>> reg.set_stop_traversal_on_missing(False)
        >>> reg.get_by_binding("a")
        {}
        >>> reg.get_by_binding("a.b")
        {}
        >>> reg.set_stop_traversal_on_missing(True)
        >>> reg.get_by_binding("a.b")
        {}
        >>> reg.get_by_binding("a.b.x")
        Traceback (most recent call last):
            ...
        KeyError: "Missing key 'x' in 'a.b'"
        """
        self.__stop_traversal_on_missing = value

    def get_by_binding(self, binding):
        """
        Search the settings tree for the given binding.

        Traverse the settings registry tree until the object at the given
        binding has been found. This will also build up the registry tree as it
        encounters missing keys from the binding, unless you have used
        set_stop_traversal_on_missing to prevent this behavior.

        If the binding is empty, or has no non-empty parts (e.g. "", ".",
        "...", etc.), then this returns the entire settings tree.

        >>> reg = SettingsRegistry()
        >>> binding_abc = reg.get_by_binding("a.b.c")
        >>> binding_ab2 = reg.get_by_binding("a.b2.key here")
        >>> binding_a = reg.get_by_binding("a")
        >>> binding_a == {'b': {'c': {}}, 'b2': {'key here': {}}}
        True
        >>> binding_abc is binding_a['b']['c']
        True
        >>> binding_ab2 is binding_a['b2']['key here']
        True
        """
        chunks = _binding_to_tuple(binding)

        obj = self.__settings_registry

        path_so_far = ''
        for chunk in chunks:
            if isinstance(obj, dict):
                if chunk not in obj:
                    if self.__stop_traversal_on_missing:
                        raise KeyError("Missing key '%s' in '%s'" %
                                       (chunk, path_so_far))

                    newdict = {}
                    obj[chunk] = newdict
                obj = obj[chunk]

                if path_so_far:
                    path_so_far += "." + chunk
                else:
                    path_so_far = chunk
            else:
                msg = ("Cannot traverse subtree of type %s "
                       "(path: '%s', key: '%s')")
                raise ValueError(msg %
                                 (type(obj).__name__, path_so_far, chunk))

        return obj

    def load_from_json(self, filename):
        """
        Load a JSON file and read its contents into the settings registry.

        Note that this will overwrite the value for any key which is already
        present in the registry.

        This method is intended to be called after registry creation, but
        before any bindings are looked up (i.e. before passing the registry to
        any object which relies on settings). For example, this is the intended
        use:

            registry = SettingsRegistry()
            registry.load_from_json('settings.json')
            # start using registry
            reporter = DeviceCloudReporter(registry)

        while use in the following manner is discouraged:

            registry = SettingsRegistry()
            # start using registry
            reporter = DeviceCloudReporter(registry)
            # load settings
            registry.load_from_json('settings.json')

        """
        with open(filename, 'r') as settings_file:
            settings = json.load(settings_file, encoding='utf-8')
            self.__settings_registry.update(settings)
