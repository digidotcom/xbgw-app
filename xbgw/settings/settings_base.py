# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Settings classes for XBee Gateway.

"""
import logging

logger = logging.getLogger(__name__)

SETTING_EMPTY = "#### setting is empty ####"


class BadSettings(Exception):

    """
    Raised when settings are rejected or not found on initialization.

    You may use the attributes 'rejected' and 'missing' to access that
    information on instances of this exception.

    Keyword arguments:
        - message: a message for this exception
        - rejected: the settings which were rejected (could not be parsed,
                    failed verification, were not declared, etc.).
                    (Default: None - will be replaced by an empty dict)
        - missing: the settings which were required but not found. (Default:
                    None - will be replaced by an empty dict)
    """

    def __init__(self, message, rejected=None, missing=None):
        # Default arguments are shared between invocations. Hence we should not
        # use default arguments of {} here.
        # http://docs.python.org/2/tutorial/controlflow.html Section 4.7.1
        if rejected is None:
            rejected = {}
        if missing is None:
            missing = {}

        self.message = message
        self.rejected = rejected
        self.missing = missing
        Exception.__init__(self, message, rejected, missing)


class SettingNotFound(Exception):
    """Raised by SettingsMixin.get_setting if the setting cannot be found."""
    pass


class Setting:

    """
    Represents a single setting in the Settings registry.

    Arguments:
        - name: the name of the settings item
        - type: a type constructor to create the item from a given value
        - parser: a function to convert any given value to a value of the
                  setting type, or raise an exception on failure. Default: None
                  (no parsing performed)
        - required: a boolean specifying if this setting is required. Default:
                    False
        - default_value: the default value for this item. Default: None
        - verify_function: a function to verify that the value is valid, e.g.
                           within range, correct size, etc. Default:
                           `lambda x: True` (always verified)
    """

    def __init__(self, name, type, parser=None, required=False,
                 default_value=None, verify_function=lambda x: True):
        self.name = name
        self.type = type
        self.parser = parser
        self.required = required
        self.default_value = default_value
        self.verify_function = verify_function

    def __repr__(self):
        kwargs = ('parser', 'required', 'default_value',
                  'verify_function')

        # Build a reasonable string representation of the arguments used to
        # construct this Setting object. This will look like:
        # 'name="foo", type=str, parser=None, ', etc.
        strings = [('name', repr(self.name)), ('type', self.type.__name__)]
        strings += [(arg, repr(getattr(self, arg))) for arg in kwargs]

        argstr = ", ".join(('%s=%s' % item for item in strings))

        return ''.join(["Setting(", argstr, ")"])

    def try_value(self, value):
        """
        Internal helper function.

        This function is used during settings validation to properly coerce
        strings (or other value types) to their defined types, as well as to
        perform validation using the 'verify_function' specified in the
        constructor.

        It is not necessary to call `try_value` yourself. Calls will be made by
        the settings infrastructure.

        """
        parsed_value = value

        if self.parser:
            parsed_value = self.parser(value)

        if not isinstance(parsed_value, self.type):
            try:
                parsed_value = self.type(value)
            except Exception, e:
                # We use %r instead of %s to represent the value because if
                # self.type is str, and str(value) raises an exception, then
                # the same exception will be raised when attempting to do
                # string formatting via %s. Also, the repr value should aid
                # more in debugging the bad value than str, since, for example,
                # str(Exception("")) == "", whereas repr(Exception("")) ==
                # 'Exception("",)'.
                # Note: If repr(value) raises an exception, then we're back
                # where we started. We assume that no exceptions will be raised
                # by repr, however.
                msg = "%r cannot be instantiated as '%s'" % \
                    (value, self.type.__name__)
                raise AttributeError(msg)

        # TBD: Should we have specialized exceptions for these cases (e.g.
        # SettingVerificationError, SettingNotVerified, etc.)?
        try:
            verified = self.verify_function(parsed_value)
        except Exception, e:
            msg = "'%s' fails verification: %s" % (value, str(e))
            raise AttributeError(msg)

        if isinstance(verified, bool) and not verified:
            msg = "'%s' failed verification function" % value
            raise AttributeError(msg)

        return parsed_value


class SettingsMixin(object):

    """
    Provides easy binding and access to the settings registry.

    The SettingsMixin class acts as a thin wrapper around the SettingsRegistry
    class, providing the same get/set capabilities on individual settings while
    restricting access to any setting which isn't explicitly registered.

    For example, if an object using this mixin binds to "my_settings.group1",
    and registers settings named "one" and "two", then the only settings
    accessible using `get_settings` will be "one" and "two" (both of these
    residing just under the "group1" key, which resides under the "my_settings"
    key in the settings tree). Attempting to access any other setting is an
    error, and will raise SettingNotFound.

    Important note: When using SettingsMixin as a mixin for your class (e.g. to
    provide access to settings in a custom component of the application), you
    MUST call SettingsMixin.__init__(self) before register_settings. There are
    internal variables created by the __init__ method which are necessary for
    the other methods to function correctly.

    Example usage:

        class MyClass(SettingsMixin):
            def __init__(self, settings_registry, settings_binding="my class"):
                SettingsMixin.__init__(self)
                verify_what_to_say = lambda s: len(s) > 0
                settings_list = [
                    Setting(name="what to say", type=str,
                            verify_function=verify_what_to_say)
                ]
                self.register_settings(settings_registry, settings_binding,
                                       settings_list)

                # Other initialization code for MyClass ...

            def say_something(self):
                message = self.get_setting("what to say")
                print message

    """

    def __init__(self):
        """
        Initialize internal variables and state.
        """
        self.__setting_list = []
        self.__settings_binding = None
        self.__settings_definitions = {}
        self.__settings = {}
        # Track whether register_settings has been called.
        self.__registered_settings = False

    def register_settings(self, registry, binding, settings):
        """
        Bind access to the settings registry, and verify the given settings.

        If any settings are missing or rejected, this method will raise
        BadSettings.

        Arguments:
            - registry: the SettingsRegistry instance to bind to
            - binding: the binding to which settings access will be restricted
            - settings: a list of Setting objects; `get_setting` will limit
                        access to only settings declared in this list
        """
        # An empty settings list means no settings are checked or accessible,
        # in which case it would be simpler to not use SettingsMixin at all.
        if not len(settings):
            logger.warn(("No settings registered for binding %s; consider "
                        "adding settings, or removing SettingsMixin"), binding)

        if self.__registered_settings:
            # register_settings has already been called
            logger.warn("register_settings was already called once with %s",
                        self.__settings_binding)

        self.__registered_settings = True

        self.__setting_list = settings
        self.__settings_binding = binding

        # Turn the settings list into a mapping from name -> setting definition
        self.__settings_definitions = {}
        for setting in settings:
            self.__settings_definitions[setting.name] = setting

        self.__settings = registry.get_by_binding(binding)

        accepted, rejected, missing = self.check_settings()
        if len(rejected) or len(missing):
            msg = "Settings rejected/missing: %s/%s" % (rejected, missing)
            raise BadSettings(msg, rejected, missing)

        self.commit_settings(accepted)

    def commit_settings(self, accepted_settings):
        """
        Update the settings registry using the dictionary of values passed in.

        It is not necessary to call `commit_settings` yourself. Calls will be
        made by `register_settings`, passing in only the verified settings.

        Arguments:
            - accepted_settings: a dictionary mapping setting
        """
        self.__settings.update(accepted_settings)

    def check_settings(self):
        """
        Verify the current settings, and apply default or parsed values.

        If a setting is missing but not required, it will be added to the
        registry with the default value specified in its declaration.

        It is not necessary to call `check_settings` yourself. Calls will be
        made by `register_settings`.

        Return value:
            (accepted, rejected, missing)
            - accepted: A dictionary containing settings whose values are
                        accepted. Each key is a setting name, and each value is
                        the accepted value for that setting.
            - rejected: A dictionary containing settings whose values were
                        rejected. Settings are rejected if calling `try_value`
                        with the current registry value leads to an exception.
                        Each key is a setting name, and each value is a tuple
                        of (current value, rejection reason).
            - missing:  A dictionary containing required settings which are not
                        found in the registry. Each key is a setting name, and
                        each value is the string "Required setting not given."
        """
        accepted, rejected, missing = {}, {}, {}

        for setting_name, value in self.__settings.iteritems():
            if setting_name not in self.__settings_definitions:
                # Skip unknown settings for now. We may revisit this later and
                # decide to do something here, such as rejecting the setting.
                # (This behavior could be a configuration option, for example.)
                logger.debug("Skipping unknown setting '%s'", setting_name)
                continue

            try:
                defn = self.__settings_definitions[setting_name]
                parsed_value = defn.try_value(value)
                accepted[setting_name] = parsed_value
            except Exception, e:
                rejected[setting_name] = (value, str(e))

        for setting_name, defn in self.__settings_definitions.iteritems():
            if setting_name not in accepted:
                if defn.required:
                    missing[setting_name] = "Required setting not given."
                else:
                    accepted[setting_name] = defn.default_value

        return accepted, rejected, missing

    def get_setting(self, name):
        """
        Look up and return the current value of a setting.

        If there is no setting by the given name (either because it was not
        declared, or because it was removed from the registry), this method
        will raise SettingNotFound.

        Arguments:
            - name: the name of the setting to look up
        """
        # If register_settings has not been called, get_setting will always
        # raise SettingNotFound
        if not self.__registered_settings:
            logger.warn("get_setting called before register_settings!")

        if name in self.__settings_definitions and name in self.__settings:
            return self.__settings[name]

        raise SettingNotFound("Setting '%s' not found" % name)
