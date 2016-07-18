#!/usr/bin/python2.7

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

# imports

import sys, os
import re
import shutil
import tempfile
import py_compile
import zipfile
import string
import distutils.sysconfig

from modulefinder import ModuleFinder

# constants

EXCLUDE_MODS = [
    # Common OS specific modules that ModuleFinder likes to suck in.
    # We don't run these OSes
    "ntpath",
    "macpath",
    "os2emxpath",
    "nturl2path",
    "macurl2path",

    # Other things that can get in the way, and don't seem likely
    "gopherlib",
    #"ftplib",
    "pydoc",

    # Files that should be in Digi's python.zip already
    "Queue",
    "StringIO",
    "__future__",
    "atexit",
    "bdb",
    "cmd",
    "code",
    "codeop",
    "copy_reg",
    "linecache",
    "os",
    "pdb",
    "posixpath",
    "pprint",
    "random",
    "re",
    "repr",
    "socket",
    "sre",
    "sre_compile",
    "sre_constants",
    "sre_parse",
    "stat",
    "string",
    "threading",
    "types",
    "warnings",
    "codecs",
    "traceback",

    # X2e has pretty much the whole standard library
    "UserDict",
    "_abcoll",
    "_weakrefset",
    "abc",
    "asyncore",
    "base64",
    "bisect",
    "calendar",
    "collections",
    "copy",
    "difflib",
    "dis",
    "distutils",
    "doctest",
    "dummy_thread",
    "encodings",
    "encodings/aliases",
    "encodings/utf_8",
    "fnmatch",
    "functools",
    "getopt",
    "gettext",
    "gzip",
    "heapq",
    "inspect",
    "io",
    "json",
    "keyword",
    "locale",
    "logging",
    "opcode",
    "optparse",
    "py_compile",
    "shutil",
    "struct",
    "tarfile",
    "tempfile",
    "textwrap",
    "token",
    "tokenize",
    "unittest",
    "unittest/case",
    "unittest/loader",
    "unittest/main",
    "unittest/result",
    "unittest/runner",
    "unittest/signals",
    "unittest/suite",
    "unittest/util",
    "weakref",
    "xml",

]

# data types
class BuildZipDescriptor:
    def __init__(self):
        self.input_script = ""
        self.output_file = ""
        self.always_analyze = []
        self.include_paths = []
        self.exclude_files = []
        self.exclude_modules = []
        self.rewrite_rules = []
        self.verbose = False
        self.compile = True
        self.compiler = None

    def __convert_paths(self, in_list):
        return [ os.path.abspath(p) for p in in_list ]

    def convert_paths(self):
        self.always_analyze = self.__convert_paths(self.always_analyze)
        self.include_paths = self.__convert_paths(self.include_paths)
        self.exclude_files = self.__convert_paths(self.exclude_files)
        self.rewrite_rules = zip(self.__convert_paths(
                                    [i[0] for i in self.rewrite_rules]),
                                 [i[1] for i in self.rewrite_rules])


def _analyze_file_deps(build_zip_descriptor, file_to_analyze):
    """
Returns a path normalized list of files a file given by file_to_analyze
depends upon.
    """
    mf = ModuleFinder(excludes=build_zip_descriptor.exclude_modules)
    mf.run_script(file_to_analyze)

    file_list = [ ]
    for module_name in mf.modules.keys():
        module_file = mf.modules[module_name].__file__
        if not module_file:
            continue
        file_list.append(os.path.abspath(module_file))

    return file_list


def build_zip(build_zip_descriptor):

    bzd = build_zip_descriptor

    # convert paths in descriptor to absolute paths in order to
    # consistently apply the rewriting rules:
    bzd.convert_paths()

    # Add include paths:
    for path in filter(lambda p: p not in sys.path, bzd.include_paths):
        sys.path.append(path)

    # Take lib-tk out of sys.path, we do not need it.
    sys.path = filter(lambda x: string.find(x, "lib-tk") == -1, sys.path)

    # Take plat-mac out of sys.path, we do not need it.
    sys.path = filter(lambda x: string.find(x, "plat-mac") == -1, sys.path)

    cleanup_tasks = [ ]

    # Begin analysis:
    files_to_analyze = [ bzd.input_script, ]

    print "Analyzing files..."
    for file_or_path in bzd.always_analyze:
        if not os.path.isdir(file_or_path):
            files_to_analyze.append(file_or_path)
        else:
            for root, dirs, files in os.walk(file_or_path):
                for name in files:
                    files_to_analyze.append(os.path.join(root, name))

    py_re = re.compile(".*\.py$")
    files_to_analyze = filter(lambda fn: py_re.match(fn), files_to_analyze)
    files_to_analyze = map(lambda fn: os.path.abspath(fn), files_to_analyze)

    file_list = [ ]
    for file_to_analyze in files_to_analyze:
        if bzd.verbose:
            print "Analyzing file: %s" % (file_to_analyze)
        new_files = _analyze_file_deps(bzd, file_to_analyze)
        file_list += new_files

    file_list = map(lambda fn: os.path.abspath(fn), file_list)
    file_list = filter(lambda fn: py_re.match(fn), file_list)
    if sys.platform.startswith("win32"):
        # os.path.samefile not available:
        for exclude_file in ([bzd.input_script,] + bzd.exclude_files):
            exclude_file = os.path.abspath(exclude_file)
            file_list = filter(lambda fn: fn != exclude_file, file_list)
    else:
        for exclude_file in ([bzd.input_script,] + bzd.exclude_files):
            file_list = filter(lambda fn: not os.path.samefile(fn,
                                exclude_file), file_list)
    # unique-ify list:
    file_list = list(set(file_list))

    # perform path rewriting according to re-write rules:
    dest_paths = {}
    if sys.platform.startswith('win32'):
        # case insensitive rewrite matching patters on win32
        rewrite_expr_map = [ (re.compile(
                                "^" + re.escape(e) + "[/\\\\]?", re.I),
                              re.escape(s)) for e, s in bzd.rewrite_rules ]
    else:
        rewrite_expr_map = [ (re.compile(
                                "^" + re.escape(e) + "[/\\\\]?"),
                              s) for e, s in bzd.rewrite_rules ]


    for f in file_list:
#        print "Processing: %s" % f
        rewrite_expr_matched = False
        for rewrite_re, rewrite_sub in rewrite_expr_map:
            if rewrite_re.match(f):
#                print "\tMATCHED."
#                print "\t'%s' will be subbed with '%s'" % (f, rewrite_sub)
                rewrite_expr_matched = True
                dest_paths[f] = rewrite_re.sub(rewrite_sub, f)
                break
        if not rewrite_expr_matched:
#            print "\tNO MATCH."
            dest_paths[f] = f


    # Copy files to temporary directory:
    if bzd.compile:
        print "Compiling files..."
    else:
        print "Copying files..."
    tmp_dir = tempfile.mkdtemp()
    try:
        cleanup_tasks.append(lambda: map(lambda t: os.rmdir(t[0]),
                                            os.walk(tmp_dir,topdown=False)))
        new_file_list = [ ]
        if bzd.verbose:
            print "Creating temporary directory: %s" % (tmp_dir)
        for f in file_list:
            dest_path = os.path.join(tmp_dir, os.path.dirname(dest_paths[f]))
            dest_file = os.path.join(dest_path, os.path.basename(dest_paths[f]))
            dest_file += 'c'
            if not os.path.exists(dest_path):
                os.makedirs(dest_path)
            try:
                if bzd.compile:
                    if bzd.compiler is not None:
                        bzd.compiler(file=f, cfile=dest_file, doraise=True)
                    else:
                        py_compile.compile(file=f, cfile=dest_file,
                                           doraise=True)
                    if bzd.verbose:
                        print "Compiled %s to %s" % (f, dest_file)
                else:
                    shutil.copy2(f, dest_file)
                    if bzd.verbose:
                        print "Copied %s to %s" % (f, dest_file)
            except Exception, e:
                del(dest_paths[f])
                continue
            new_file_list.append(dest_file)
            if bzd.compile:
                dest_paths[dest_file] = dest_paths[f] + 'c'
            else:
                dest_paths[dest_file] = dest_paths[f]
            del(dest_paths[f])
        file_list = list(set(new_file_list))
        cleanup_tasks.insert(0, lambda: map(lambda f: os.remove(f), file_list))


        # Generate file archive:
        print "Zipping files..."
        if bzd.verbose:
            print "Writing to file: %s" % (bzd.output_file)
        if (len(list(file_list)) > 0):
            zf = zipfile.ZipFile(bzd.output_file, 'w', zipfile.ZIP_DEFLATED)
            for f in file_list:
                if bzd.verbose:
                    print "Adding %s as %s" % (f, dest_paths[f])
                try:
                    zf.write(f, dest_paths[f])
                except:
                    print "Warning: couldn't add file %s" % (f)
            zf.close()

            print "Finished writing archive '%s'" % (bzd.output_file)
        else:
            print "This file has not any module dependency."
            sys.exit(-1)
    finally:
        if bzd.verbose:
            print "Cleaning up..."
        for task in cleanup_tasks:
            task()


