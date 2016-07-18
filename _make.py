# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

import tools.build_zip as build_zip
import os
import sys
import distutils.sysconfig

PYTHON_LIB = distutils.sysconfig.get_python_lib(False,True)

ARGV0_DIRNAME, ARGV0_BASENAME = os.path.split(sys.argv[0])
if ARGV0_DIRNAME == '':
    ARGV0_DIRNAME = os.getcwd()

DEFAULT_SOURCE="xbgw_main.py"

ALWAYS_ANALYZE = (
                os.path.join(sys.path[0], DEFAULT_SOURCE),
                #os.path.join(PYTHON_LIB, "encodings/utf_8.py"),
    )

EXCLUDE_FILES = (
                  os.path.join(sys.path[0], DEFAULT_SOURCE),
    )

INCLUDE_PATHS = (
                  #distutils.sysconfig.get_python_lib(False,True),
                  # os.path.join(ARGV0_DIRNAME, 'lib'),
                  # os.path.join(ARGV0_DIRNAME, 'src'),
                  os.getcwd(),
    )

REWRITE_RULES = (
                  (distutils.sysconfig.get_python_lib(False,True), ""),
                  # (os.path.join(ARGV0_DIRNAME, 'lib'), os.path.join('lib', '')),
                  # (os.path.join(ARGV0_DIRNAME, 'src'), os.path.join('src', '')),
                  ("venv/local/lib/python2.7/site-packages", ""),
                  ("venv/lib/python2.7", ""),
                  (os.getcwd(), ""),
    )

# add project include paths to system path:
for include_path in INCLUDE_PATHS:
    sys.path.append(include_path)

bzd = build_zip.BuildZipDescriptor()

bzd.input_script = "xbgw_main.py"
bzd.output_file = "xbgw.zip"
bzd.exclude_modules = build_zip.EXCLUDE_MODS
bzd.always_analyze = ALWAYS_ANALYZE
bzd.include_paths = INCLUDE_PATHS
bzd.rewrite_rules = REWRITE_RULES
bzd.verbose = True

build_zip.build_zip(bzd)

