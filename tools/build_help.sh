# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

# Common shell functions used by the various shell scripts for
# building, testing, etc.

mk_venv () {
    # Is virtualenv installed? If so, use it to create a virtual environment
    if [ $(command -v virtualenv) ]
    then
        echo "Using system virtualenv to create virtual environment..."
        virtualenv venv
    else
        # Check this system has python2.7 installed.
        if ! type python2.7 >/dev/null ; then
            echo "Error: python2.7 command could not be found."
            exit 1
        fi

        rm virtualenv-pypi/ -rf
        VENV_TGZ=tools/virtualenv-1.11.1.tar.gz
        VENV_URL=https://pypi.python.org/packages/source/v/virtualenv/virtualenv-1.11.1.tar.gz
        if [ ! -f $VENV_TGZ ]; then
            echo "Downloading virtualenv from PyPI."
            # Virtualenv not in tools; download it from PyPI
            curl $VENV_URL > $VENV_TGZ
        fi
        # Delete any existing virtualenv-pypi directory
        mkdir virtualenv-pypi
        tar xzf $VENV_TGZ -C virtualenv-pypi
        # Create a virtual environment.
        echo "Creating virtual environment..."
        python virtualenv-pypi/virtualenv-1.11.1/virtualenv.py --python=python2.7 venv
        # Remove virtualenv-pypi directory, as it's not needed.
        rm virtualenv-pypi/ -rf
    fi
}

venv_activate () {
    if [ -d venv/bin ]; then
        . venv/bin/activate
    else
        if [ -d venv/Scripts ]; then
            . venv/Scripts/activate
        else
            echo "Cannot find virtualenv bin or Scripts directory!"
            exit 1
        fi
    fi
}

install_requirements () {
    # Add required pip install flags if pip version >= 1.5
    FLAGS=""
    PIP15=`python -c 'import tools; print tools.pip15_or_higher()'`
    if [ "$PIP15" = "True" ]; then
        echo "Pip 1.5 or higher is being used."
        FLAGS="--allow-all-external --allow-unverified PyPubSub"
    fi

    echo "Installing Python library dependencies..."
    pip install -q -r requirements.txt $FLAGS
}

create_environment() {
    if [ ! -d venv ]
    then
        mk_venv
    fi
    venv_activate
    install_requirements
}
