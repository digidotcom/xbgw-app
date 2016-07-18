XBee Gateway App
================

The XBee Gateway App is a Python application that runs on the
Digi [XBee Gateway][XBGW] and uses its API to connect your XBee
modules to [Device Cloud][DeviceCloud]. This application is loaded
by default on XBee Gateway.

This source has been contributed by [Digi International][Digi].
This is a RELEASE software release which has been fully QA-tested and supported
by Digi International.

[Digi]: http://www.digi.com
[XBGW]: http://www.digi.com/products/xbee-rf-solutions/gateways/xbee-gateway
[DeviceCloud]: http://www.digi.com/products/cloud/digi-device-cloud


Requirements and Setup
----------------------

The XBee Gateway Python application requires the use of [Python 2.7][].

The provided build and deployment scripts depend on a POSIX-compatible shell
environment, as well as the following tools: `ssh`, `scp`, `curl`, `tar` and
`zip`. If you are developing on Windows, you will need to use
[Cygwin](https://cygwin.com) with the openssh package installed.

 1. Ensure [Python 2.7][] is installed. (If using Cygwin on Windows, install
    the `python` package using the Cygwin setup utility.)
 2. Clone this Git repository, or download the code using the Download button
    above.
 3. Run the provided unit tests; this will serve to check that your system is
    ready to build and deploy the application.

        $ ./test.sh
        ...
        (output truncated)
        ...
        ----------------------------------------------------------------------
        Ran 157 tests in 0.548s

        OK

 4. (Optional) Deploy the application onto an XBee Gateway. Replace
    `<ipaddr>` below with the IP address of the XBee Gateway.

        $ ./deploy.sh <ipaddr>

    This will byte-compile the code, copy it onto the gateway, and start the
    application. You will see output similar to this:

        Aug  4 19:44:06 (none) local7.info pylog: 2014-08-04 19:44:06,804 INFO root: XBGW App Version: 1.1.0b2
        Aug  4 19:44:06 (none) local7.info pylog: 2014-08-04 19:44:06,860 INFO xbgw.xbee.manager: Initializing XBeeEventManager
        Aug  4 19:44:06 (none) local7.info pylog: 2014-08-04 19:44:06,934 INFO xbgw.xbee.ddo_manager: Initializing DDOEventManager
        Aug  4 19:44:07 (none) local7.info pylog: 2014-08-04 19:44:07,030 INFO xbgw.reporting.device_cloud: Initializing DeviceCloudReporter
        Aug  4 19:44:07 (none) local7.info pylog: 2014-08-04 19:44:07,072 INFO xbgw.command.rci: RCICommandProcessor initialized

[Python 2.7]: https://www.python.org/download/releases/2.7/


Application Design
==================

## Built on asyncore

The XBee Gateway App is built primarily on Python's [`asyncore`][asyncore] module.

[asyncore]: https://docs.python.org/2/library/asyncore.html

The XBee Gateway App uses asyncore to handle communication with XBee sockets in
Python. Instead of needing to write a loop to poll/select on the sockets, we
just need to create a few `asyncore.dispatcher` objects to take care of reading
and processing data from the sockets. See the `DDOEventManager` class
in [xbgw/xbee/ddo_manager.py](xbgw/xbee/ddo_manager.py) for an example of this.

## Built on PyPubSub

The XBee Gateway App also uses the Python [PubSub][] library to send messages
and data between different parts of the app.

[PubSub]: http://pubsub.sourceforge.net/

> The Pubsub package provides a publish - subscribe Python API that facilitates
> event-based programming. Using the publish - subscribe pattern in your
> application can dramatically simplify its design and improve testability.

## Application Components

The XBee Gateway App is designed with two main types of components:
event managers, and reporters.

### Event Managers

An "event manager" in the XBee Gateway App is a component that takes input from
outside of the application (for example, RCI commands or XBee socket messages),
processes that input in some way, and sends information to the rest of the
application using PubSub messages.

Examples of event managers in the app are:

  * XBee socket managers (see
    [manager.py](xbgw/xbee/manager.py) and
    [ddo_manager.py](xbgw/xbee/ddo_manager.py))
  * RCI command listeners, such as the XBee socket managers
    (which implement the "send_serial" and "set_digital_output" commands)
    and various [example commands](xbgw/debug/).

Event managers are typically implemented to be entirely asynchronous, but
depending on the needs of an application, an event manager could run on its own
thread and thus have a synchronous/blocking implementation.

### Reporters

A "reporter" in the XBee Gateway App is a component that takes input from
within the application (via PubSub messages) and transmits data to the outside
world, e.g. to a cloud service such as [Digi Device Cloud][DeviceCloud].

Depending on the application needs (and the means of communicating with
external services), reporters can be implemented either asynchronously (e.g.
using an asyncore dispatcher) or using a background thread.

The only reporter currently implemented is the
[Device Cloud reporter](xbgw/reporting/device_cloud.py), which uploads messages
to [Digi Device Cloud][DeviceCloud] as data points.

### RCI Command Processing

See the docstring at the top of the [rci.py](xbgw/command/rci.py) module for
information on how RCI commands are made available to the application. You may
also refer to the [provided debug commands](xbgw/debug/) for simple examples of
RCI command implementations.

### Application Settings

The behavior of the XBee Gateway App can be configured using settings stored in
[xbgw_settings.json](xbgw_settings.json). This file is parsed and converted
into the [Settings Registry](xbgw/settings/registry.py). Application components
can "register" themselves with this Settings Registry to specify their own
configuration values which can be overridden by the settings file.

See [xbgw/debug/settings_example.py](xbgw/debug/settings_example.py) for
a small example of an application component which uses the settings registry.
You can also refer to the XBeeEventManager class
(found [here](xbgw/xbee/manager.py)) for an example of real code using multiple
settings.

The default settings for the application are as follows:

  * Device Cloud ("devicecloud"):
    * `"encode serial"`: `true`. If set to true, received serial data will be
      converted to base64 encoding before upload to Device Cloud. base64
      encoding of data avoids issues with whitespace, commas, and newline
      characters in data
  * XBee event manager ("xbee_manager"):
    * `"filter_analog_duplicates"`: `true`. If set to true, the application
      will remember past analog samples from each XBee and ignore samples when
      they match the previous value.
    * `"minimum_analog_change"`: `1`. This setting is used when
      `"filter_analog_duplicates"` is set to true. This specifies the minimum
      amount by which an analog value must change from the previous reported
      sample before reporting a new value.
    * `"filter_digital_duplicates"`: `1`. If set to true, the application will
      remember past digital I/O values from each XBee and ignore a pin's value
      when it matches the previous value.

## Running the App

The starting point of the XBee Gateway App is in the
[xbgw_main.py](xbgw_main.py) script.

`xbgw_main.py` imports and initializes the various components of the
application, sets up message subscriptions for the Device Cloud reporter, and
kicks off the main asyncore `loop` call.

Since the main thread is occupied with the `asyncore.loop()` call, any
background processing or data uploads must either be implemented using
`asyncore` (as with the XBee socket managers), or using a background thread
(as with the Device Cloud reporter).


License
=======

This software is open-source software. Copyright Digi International Inc., 2016.

This Source Code form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this file,
you can obtain one at http://mozilla.org/MPL/2.0/.
