# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

def pip15_or_higher():
    import pip
    if getattr(pip, "__version__", None) is None:
        # pip.__version__ does not exist. Must be 1.1 or earlier.
        return False
    version = tuple(int(p) for p in pip.__version__.split('.'))
    return version >= (1,5)
