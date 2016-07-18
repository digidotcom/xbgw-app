# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from xbgw.settings.settings_base import Setting
from nose.tools import eq_, assert_raises
from hamcrest import assert_that, ends_with


# A very basic Setting, with type=str, should coerce input values to strings.
def test_basic_string_setting():
    uut = Setting("test_setting", type=str)

    # String values
    eq_(uut.try_value("ABC"), "ABC")
    eq_(uut.try_value("xyz"), "xyz")
    eq_(uut.try_value("Hello, World"), "Hello, World")

    # Check that non-string values are coerced to string
    eq_(uut.try_value(512), "512")
    eq_(uut.try_value(None), "None")
    eq_(uut.try_value(True), "True")

    # There is no failure case for this simple UUT, unless we pass in a value
    # whose __str__ method raises an Exception.


# try_value should not try to use the type constructor if the parser function
# returns a value of the given type.
def test_no_coerce_if_parser_works():
    # Class which raises an Exception when __str__ is called (i.e. when an
    # object of this class is passed into str()). This will be used to check
    # whether str() is used on the passed-in value.
    class StrException(object):
        def __str__(self):
            raise ValueError

    parser = lambda v: "return value"
    uut = Setting("test setting", type=str, parser=parser)
    test_value = StrException()

    eq_(uut.try_value(test_value), "return value")


# try_value SHOULD try to use the type constructor if the parser function does
# not return a value of the given type.
def test_coerce_if_parser_does_not_work():
    # Class which raises an Exception when __str__ is called (i.e. when an
    # object of this class is passed into str()). This will be used to check
    # whether str() is used on the passed-in value.
    class StrException(object):
        def __str__(self):
            raise ValueError("StrException message")

    parser = lambda v: ("A string in a tuple does not a string make.",)
    uut = Setting("test setting", type=str, parser=parser)
    test_value = StrException()

    with assert_raises(AttributeError) as caught:
        uut.try_value(StrException())

    assert_that(caught.exception.message,
                ends_with("cannot be instantiated as 'str'"))


# try_value should raise an AttributeError with an appropriate message if the
# verify_function raises an Exception
def test_verify_exception():
    def verify_fn(value):
        raise Exception("Some exception")

    uut = Setting("test", type=str, verify_function=verify_fn)

    with assert_raises(AttributeError) as caught:
        uut.try_value("some value")

    eq_(caught.exception.message,
        "'some value' fails verification: Some exception")


# The verify_function argument should be used to verify/validate any input
# value.
def test_string_setting_verify_error():
    verify_fn = lambda value: len(value) > 0

    uut = Setting("test setting", type=str, verify_function=verify_fn)

    with assert_raises(AttributeError) as caught:
        uut.try_value("")

    eq_(caught.exception.message, "'' failed verification function")


def do_setting_coerce_error(type_constructor, value):
    uut = Setting("test", type=type_constructor)

    type_name = type_constructor.__name__

    expected_message = "%r cannot be instantiated as '%s'" % (value, type_name)

    with assert_raises(AttributeError) as caught:
        uut.try_value(value)

    eq_(caught.exception.message, expected_message)


# Test various type-value combinations to check for failure to coerce types.
def test_coercion_failure():
    yield do_setting_coerce_error, int, "not an int"  # string
    yield do_setting_coerce_error, int, "0x10"  # hex value
    yield do_setting_coerce_error, int, object()
    yield do_setting_coerce_error, int, None
    yield do_setting_coerce_error, int, []

    yield do_setting_coerce_error, float, "0.0.0"
    yield do_setting_coerce_error, float, []
    yield do_setting_coerce_error, float, None

    yield do_setting_coerce_error, tuple, None
    yield do_setting_coerce_error, tuple, 123

    yield do_setting_coerce_error, list, None
    yield do_setting_coerce_error, list, 122
