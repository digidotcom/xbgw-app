#!/bin/sh
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

. tools/build_help.sh

# Make sure the zip command is available.
if ! type zip >/dev/null ; then
    echo "Error: zip command could not be found."
    exit 1
fi

store_build_data(){
    if [ -n "$BUILD_BRANCH" ]
    then
        # Extract build version from BUILD_BRANCH environment variable.
        VERSION=${BUILD_BRANCH#release/xbgw-}

        if [ "$VERSION" != "$BUILD_BRANCH" ]
        then
            VERSION="${VERSION}b${BUILD_NUMBER}"
            # Release build
            cat > build.py <<EOF
EOF
        else
            # Regular test build
            VERSION="${BUILD_BRANCH} (#${BUILD_NUMBER})"
            cat > build.py <<EOF
build_number = "${BUILD_NUMBER}"
build_branch = "${BUILD_BRANCH}"
EOF
        fi
    else
        # Developer machine
        BUILD_HOST=$(uname -n)
        BUILD_TIME=$(date -Iseconds)
        BUILD_REV=$(git rev-parse HEAD)
        VERSION="${BUILD_HOST} - ${BUILD_TIME}"
        cat > build.py <<EOF
build_host = "${BUILD_HOST}"
EOF

    fi

    # Content for all build.py
    cat >> build.py <<EOF
build_rev = "${BUILD_REV}"
build_time = "${BUILD_TIME}"
version = "${VERSION}"
EOF

}

# Install venv, activate it and grab requirements
create_environment

python _make.py

# Byte-compile the pubsub library
cd venv/lib/python2.7/site-packages
python -m compileall pubsub

# Don't need to be in virtual environment anymore
deactivate

# Collect all of pubsub into xbgw.zip
find pubsub -name "*.pyc" -print0 |xargs -0 zip ../../../../xbgw.zip

cd -

store_build_data
