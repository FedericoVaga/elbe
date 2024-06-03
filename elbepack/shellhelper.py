# ELBE - Debian Based Embedded Rootfilesystem Builder
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2014-2017 Linutronix GmbH
# SPDX-FileCopyrightText: 2014 Ferdinand Schwenk <ferdinand.schwenk@emtrion.de>

import logging
import os
import shlex
import subprocess

from elbepack.log import async_logging_ctx


def _is_shell_cmd(cmd):
    return isinstance(cmd, str)


def _log_cmd(cmd):
    if _is_shell_cmd(cmd):
        return cmd
    else:
        return shlex.join(map(os.fspath, cmd))


def do(cmd, /, *, check=True, env_add=None, log_cmd=None, **kwargs):
    """do() - Execute cmd in a shell and redirect outputs to logging.

    Throws a subprocess.CalledProcessError if cmd returns none-zero and check=True

    --

    Let's redirect the loggers to current stdout
    >>> import sys
    >>> from elbepack.log import open_logging
    >>> open_logging({"streams":sys.stdout})

    >>> do("true")
    [CMD] true

    >>> do("false", check=False)
    [CMD] false

    >>> do("cat -", input=b"ELBE")
    [CMD] cat -

    >>> do("cat - && false", input=b"ELBE") # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    subprocess.CalledProcessError: ...

    >>> do("false") # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    subprocess.CalledProcessError: ...
    """

    new_env = os.environ.copy()
    if env_add:
        new_env.update(env_add)

    logging.info(log_cmd or _log_cmd(cmd), extra={'context': '[CMD] '})

    with async_logging_ctx() as w:
        subprocess.run(cmd, shell=_is_shell_cmd(cmd), stdout=w, stderr=subprocess.STDOUT,
                       env=new_env, check=check, **kwargs)


def chroot(directory, cmd, /, *, env_add=None, **kwargs):
    """chroot() - Wrapper around do().

    --

    Let's redirect the loggers to current stdout

    >>> import sys
    >>> from elbepack.log import open_logging
    >>> open_logging({"streams":sys.stdout})

    >>> chroot("/", "true") # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    subprocess.CalledProcessError: ...
    """

    new_env = {'LANG': 'C',
               'LANGUAGE': 'C',
               'LC_ALL': 'C'}
    if env_add:
        new_env.update(env_add)

    if _is_shell_cmd(cmd):
        do(['/usr/sbin/chroot', directory, '/bin/sh', '-c', cmd], env_add=new_env, **kwargs)
    else:
        do(['/usr/sbin/chroot', directory] + cmd, env_add=new_env, **kwargs)


def get_command_out(cmd, /, *, check=True, env_add=None, **kwargs):
    """get_command_out() - Like do() but returns stdout.

    --

    Let's quiet the loggers

    >>> import os
    >>> from elbepack.log import open_logging
    >>> open_logging({"files":os.devnull})

    >>> get_command_out("echo ELBE")
    b'ELBE\\n'

    >>> get_command_out("false") # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    subprocess.CalledProcessError: ...

    >>> get_command_out("false", check=False)
    b''

    >>> get_command_out("cat -", input=b"ELBE", env_add={"TRUE":"true"})
    b'ELBE'
    """

    new_env = os.environ.copy()

    if env_add:
        new_env.update(env_add)

    logging.info(_log_cmd(cmd), extra={'context': '[CMD] '})

    with async_logging_ctx() as w:
        ps = subprocess.run(cmd, shell=_is_shell_cmd(cmd), stdout=subprocess.PIPE, stderr=w,
                            env=new_env, check=check, **kwargs)
        return ps.stdout


def env_add(d):
    env = os.environ.copy()
    env.update(d)
    return env
