# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Tools for working with locks

A lock is just an empty directory. We use directories because this lets us use
the race condition-proof os.makedirs.

For now, there is one global lock for all of conda, because some things happen
globally (such as downloading packages).

We don't raise an error if the lock is named with the current PID
"""
from glob import glob
import logging
import os
from os.path import abspath, basename, dirname, isdir, join
import time

from .deprecations import deprecated
from .exceptions import LockError

deprecated.module("23.3", "23.9", addendum="Use `filelock` instead.")

LOCK_EXTENSION = 'conda_lock'

# Keep the string "LOCKERROR" in this string so that external
# programs can look for it.
LOCKSTR = """
LOCKERROR: It looks like conda is already doing something.
The lock {0} was found. Wait for it to finish before continuing.
If you are sure that conda is not running, remove it and try again.
You can also use: $ conda clean --lock
"""

log = logging.getLogger(__name__)
stdoutlog = logging.getLogger('conda.stdoutlog')

def touch(file_name, times=None):
    """ Touch function like touch in Unix shell
    :param file_name: the name of file
    :param times: the access and modified time
    Examples:
        touch("hello_world.py")
    """
    try:
        with open(file_name, 'a'):
            os.utime(file_name, times)
    except OSError as e:
        log.warn("Failed to create lock, do not run conda in parallel processes [errno %d]",
                 e.errno)


class FileLock:
    """Lock a path (file or directory) with the lock file sitting *beside* path.

    :param path_to_lock: the path to be locked
    :param retries: max number of retries
    """
    def __init__(self, path_to_lock, retries=10):
        """
        """
        self.path_to_lock = abspath(path_to_lock)
        self.retries = retries
        self.lock_file_path = f"{self.path_to_lock}.pid{{0}}.{LOCK_EXTENSION}"
        # e.g. if locking path `/conda`, lock file will be `/conda.pidXXXX.conda_lock`
        self.lock_file_glob_str = f"{self.path_to_lock}.pid*.{LOCK_EXTENSION}"
        assert isdir(dirname(self.path_to_lock)), f"{self.path_to_lock} doesn't exist"
        assert "::" not in self.path_to_lock, self.path_to_lock

    def __enter__(self):
        sleep_time = 1
        self.lock_file_path = self.lock_file_path.format(os.getpid())
        last_glob_match = None

        for _ in range(self.retries + 1):

            # search, whether there is process already locked on this file
            glob_result = glob(self.lock_file_glob_str)
            if glob_result:
                log.debug(LOCKSTR.format(glob_result))
                log.debug("Sleeping for %s seconds", sleep_time)

                time.sleep(sleep_time / 10)
                sleep_time *= 2
                last_glob_match = glob_result
            else:
                touch(self.lock_file_path)
                return self

        stdoutlog.error("Exceeded max retries, giving up")
        raise LockError(LOCKSTR.format(last_glob_match))

    def __exit__(self, exc_type, exc_value, traceback):
        from .gateways.disk.delete import rm_rf
        rm_rf(self.lock_file_path)


# lgtm alert ignore because this lock functionality is unused and will soon be replaced
class DirectoryLock(FileLock):  # lgtm [py/missing-call-to-init]
    """Lock a directory with the lock file sitting *within* the directory being locked.

    Useful when, for example, locking the root prefix at ``/conda``, and ``/`` is not writable.

    :param directory_path: the path to be locked
    :param retries: max number of retries
    """

    def __init__(self, directory_path, retries=10):
        self.directory_path = abspath(directory_path)
        directory_name = basename(self.directory_path)
        self.retries = retries
        lock_path_pre = join(self.directory_path, directory_name)
        self.lock_file_path = f"{lock_path_pre}.pid{{0}}.{LOCK_EXTENSION}"
        # e.g. if locking directory `/conda`, lock file will be `/conda/conda.pidXXXX.conda_lock`
        self.lock_file_glob_str = f"{lock_path_pre}.pid*.{LOCK_EXTENSION}"
        # make sure '/' exists
        assert isdir(dirname(self.directory_path)), f"{self.directory_path} doesn't exist"
        if not isdir(self.directory_path):
            try:
                os.makedirs(self.directory_path)
                log.debug("forced to create %s", self.directory_path)
            except OSError as e:
                log.warn("Failed to create directory %s [errno %d]", self.directory_path, e.errno)


Locked = DirectoryLock
