#!/bin/sh
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

# Utility deployment script for XBee Gateway Python application.
# Builds xbgw.zip, copies application files into the Python user filesystem
# of the specified XBee Gateway, and starts the application.
# To terminate the application, press Ctrl-C.

if [ $# -lt 1 ]; then
    echo "Usage: $0 <XBee Gateway IP address>"
    exit 1
fi

case "$(uname -s)" in
    CYGWIN*)
        CYGWIN=1
        ;;
    *)
        CYGWIN=0
        ;;
esac

check_ssh_command() {
    if ! type "$1" >/dev/null ; then
        echo "Error: $1 command could not be found."
        if [ ${CYGWIN} -eq 1 ] ; then
            echo "Install the openssh package and try again."
        fi

        exit 1
    fi
}

# Make sure the scp and ssh commands are present on this system.
check_ssh_command scp
check_ssh_command ssh

DEVICE=$1
SSH_TARGET=python@$DEVICE

# Run make.sh to compile xbgw.zip
./make.sh

# Copy xbgw.zip, xbgw_main.py and the settings file to the device
scp xbgw.zip xbgw_main.py xbgw_settings.json build.py $SSH_TARGET:.

# Write the run.sh script onto the device
# (Note that the script includes 'killall python', which could be dangerous to
# other Python processes running on the device. The assumption here, though, is
# that the only Python processes running will be xbgw, and we want to kill them
# off before running again.)
ssh $SSH_TARGET "cat >/WEB/python/run.sh" <<SCRIPT
cd /WEB/python
killall python
python xbgw_main.py
SCRIPT

# Execute run.sh
ssh $SSH_TARGET 'sh /WEB/python/run.sh'
