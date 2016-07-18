# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import os
import os.path
import fcntl
import sys
import atexit

sys.path.append("xbgw.zip")

import asyncore
import logging
from pubsub import pub

from xbgw.xbee.manager import XBeeEventManager
from xbgw.xbee.ddo_manager import DDOEventManager
from xbgw.reporting.device_cloud import DeviceCloudReporter
from xbgw.command.rci import RCICommandProcessor
from xbgw.settings import SettingsRegistry

from xbgw.debug.echo import EchoCommand

try:
    from build import version
except ImportError:
    version = "None"


SETTINGS_FILE = "xbgw_settings.json"
PID_FILE = "xbgw.pid"


class PubsubExceptionHandler(pub.IListenerExcHandler):
    def __init__(self):
        pass

    def __call__(self, raiser, topicObj):
        import traceback
        tb = traceback.format_exc()
        logger = logging.getLogger()
        logger.error("PubSub caught exception in listener %s:\n%s", raiser, tb)


def main():
    setup_logging()

    logger = logging.getLogger()
    logger.info("XBGW App Version: {}".format(version))

    # Make sure we're the only instance of the app on this system
    prevent_duplicate(PID_FILE)

    # Catch and log exceptions unhandled by listeners
    pub.setListenerExcHandler(PubsubExceptionHandler())

    # Create the settings file if it does not exist already.
    # TODO: Consider moving into load_from_json as managing the
    # settings file should arguably be done by the SettingsRegistry
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            f.write("{}")

    settings = SettingsRegistry()
    settings.load_from_json(SETTINGS_FILE)

    # Create PubSub participants
    XBeeEventManager(settings, "xbee_manager")
    DDOEventManager()
    dcrep = DeviceCloudReporter(settings, "devicecloud")
    rciproc = RCICommandProcessor()
    echo_cmd = EchoCommand()

    # Subscribe to all topics that XBeeEventManager publishes
    for topic in XBeeEventManager.data_topics:
        dcrep.start_reporting(topic)

    # timeout is 30 seconds by default, but that is far too slow for our
    # purposes. Set the timeout to 100 ms. (Value may be fine tuned later)
    asyncore.loop(timeout=0.1)


def setup_logging():
    FORMAT = '%(asctime)-15s %(levelname)s %(name)s: %(message)s'
    logging.basicConfig(format=FORMAT)
    logging.getLogger().setLevel(logging.DEBUG)


def prevent_duplicate(pid_filename):
    # Make sure we're the only instance of the app on this system
    pidfile = open(pid_filename, "a+", 0)
    try:
        fcntl.flock(pidfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logging.getLogger().error(
            "Could not lock PID file, application may already be running")
        sys.exit(-1)

    # Write our PID out
    pidfile.seek(0)
    os.ftruncate(pidfile.fileno(), 0)
    pidfile.write(str(os.getpid()) + '\n')
    pidfile.flush()
    # Keep pidfile open so the lock is held by our process

    atexit.register(cleanup_pidfile, pidfile)


def cleanup_pidfile(pidfile):
    pidfile.close()
    os.remove(PID_FILE)


if __name__ == "__main__":
    main()
