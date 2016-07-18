#!/bin/sh
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

. tools/build_help.sh
# Install virtual Python environment, activate it and grab requirements
create_environment

coverage erase
# Run the tests
nosetests --with-cover --with-xunit --with-isolation
# Generate code coverage information
coverage html
# Check code quality
pylint --rcfile=pylintrc xbgw_main.py xbgw > pylint.html
pep8 xbgw_main.py xbgw > pep8.txt

# Deactivate virtual Python environment
deactivate
