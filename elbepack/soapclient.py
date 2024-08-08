# ELBE - Debian Based Embedded Rootfilesystem Builder
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2014-2018 Linutronix GmbH
# SPDX-FileCopyrightText: 2016 Claudius Heine <ch@denx.de>

import binascii
import fnmatch
import logging
import os
import socket
import sys
import time
from http.client import BadStatusLine
from urllib.error import URLError

from suds.client import Client

from elbepack.cli import CliError
from elbepack.elbexml import ElbeXML, ValidationMode
from elbepack.version import elbe_version


_logger = logging.getLogger(__name__)


class ElbeVersionMismatch(RuntimeError):
    def __init__(self, client_version, server_version):
        self.client_version = client_version
        self.server_version = server_version
        super().__init__(f'Client: {client_version} Server: {server_version}')

    @classmethod
    def check(cls, client_version, server_version):
        if client_version != server_version:
            raise cls(client_version, server_version)


class ElbeSoapClient:
    def __init__(self, host, port, user, passwd, timeout, retries=10):

        # Attributes
        self._wsdl = 'http://' + host + ':' + str(port) + '/soap/?wsdl'
        self._timeout = timeout
        self._retries = retries
        self._user = user
        self._passwd = passwd
        self.host = host
        self.port = port

    def connect(self):
        control = None
        current_retries = 0

        # Loop and try to connect
        while control is None:
            current_retries += 1
            try:
                control = Client(self._wsdl, timeout=self._timeout)
            except (URLError, socket.error, BadStatusLine):
                if current_retries > self._retries:
                    raise
                time.sleep(1)

        # Make sure, that client.service still maps
        # to the service object.
        self.service = control.service

        ElbeVersionMismatch.check(elbe_version, self.service.get_version())

        # We have a Connection, now login
        self.service.login(self._user, self._passwd)

    @classmethod
    def from_args(cls, args):
        return cls(args.soaphost, args.soapport, args.soapuser, args.soappassword,
                   args.soaptimeout, retries=args.retries)

    def download_file(self, builddir, filename, dst_fname):
        fp = open(dst_fname, 'wb')
        part = 0

        # XXX the retry logic might get removed in the future, if the error
        # doesn't occur in real world. If it occurs, we should think about
        # the root cause instead of stupid retrying.
        retry = 5

        while True:
            try:
                ret = self.service.get_file(builddir, filename, part)
            except BadStatusLine as e:
                retry = retry - 1

                print(f'get_file part {part} failed, retry {retry} times',
                      file=sys.stderr)
                print(str(e), file=sys.stderr)
                print(repr(e.line), file=sys.stderr)

                if not retry:
                    fp.close()
                    print('file transfer failed', file=sys.stderr)
                    sys.exit(170)

            if ret == 'EndOfFile':
                fp.close()
                return

            fp.write(binascii.a2b_base64(ret))
            part = part + 1

    @staticmethod
    def _upload_file(append, build_dir, filename):
        size = 1024 * 1024

        with open(filename, 'rb') as f:

            while True:

                bin_data = f.read(size)
                data = binascii.b2a_base64(bin_data)

                if not isinstance(data, str):
                    data = data.decode('ascii')

                append(build_dir, data)

                if len(bin_data) != size:
                    break

    def wait_busy(self, project_dir):
        while True:
            try:
                msg = self.service.get_project_busy(project_dir)
            # TODO the root cause of this problem is unclear. To enable a
            # get more information print the exception and retry to see if
            # the connection problem is just a temporary problem. This
            # code should be reworked as soon as it's clear what is going on
            # here
            except socket.error:
                _logger.warn('socket error during wait busy occured, retry..', exc_info=True)
                continue

            if not msg:
                time.sleep(0.1)
                continue

            if msg == 'ELBE-FINISH':
                break

            yield msg

        # exited the while loop -> the project is not busy anymore,
        # check, whether everything is ok.

        prj = self.service.get_project(project_dir)
        if prj.status != 'build_done':
            raise CliError(191, f'Project build was not successful, current status: {prj.status}')

    def set_xml(self, builddir, filename):
        x = ElbeXML(
            filename,
            skip_validate=True,
            url_validation=ValidationMode.NO_CHECK)

        if not x.has('target'):
            raise ValueError("<target> is missing, this file can't be built in an initvm")

        size = 1024 * 1024
        part = 0
        with open(filename, 'rb') as fp:
            while True:

                xml_base64 = binascii.b2a_base64(fp.read(size))

                if not isinstance(xml_base64, str):
                    xml_base64 = xml_base64.decode('ascii')

                # finish upload
                if len(xml_base64) == 1:
                    part = self.service.upload_file(builddir,
                                                    'source.xml',
                                                    xml_base64,
                                                    -1)
                else:
                    part = self.service.upload_file(builddir,
                                                    'source.xml',
                                                    xml_base64,
                                                    part)
                if part == -1:
                    raise RuntimeError('project busy, upload not allowed')
                if part == -2:
                    _logger.debug('upload of xml finished')
                    return

    def set_orig(self, builddir, orig_file):
        self.service.start_upload_orig(builddir, os.path.basename(orig_file))
        self._upload_file(self.service.append_upload_orig, builddir, orig_file)
        self.service.finish_upload_orig(builddir)

    def set_pdebuild(self, builddir, pdebuild_file, profile='', cross=False):
        self.service.start_pdebuild(builddir)
        self._upload_file(self.service.append_pdebuild, builddir, pdebuild_file)
        self.service.finish_pdebuild(builddir, profile, cross)

    def set_cdrom(self, builddir, cdrom_file):
        self.service.start_cdrom(builddir)
        self._upload_file(self.service.append_cdrom, builddir, cdrom_file)
        self.service.finish_cdrom(builddir)

    def get_files(self, builddir, outdir, *, pbuilder_only=False, wildcard=None):
        files = self.service.get_files(builddir)

        result = []

        for f in files[0]:
            if (pbuilder_only and not f.name.startswith('pbuilder_cross')
                    and not f.name.startswith('pbuilder')):
                continue

            if wildcard and not fnmatch.fnmatch(f.name, wildcard):
                continue

            result.append(f)

            if outdir:
                dst = os.path.abspath(outdir)
                os.makedirs(dst, exist_ok=True)
                dst_fname = str(os.path.join(dst, os.path.basename(f.name)))
                self.download_file(builddir, f.name, dst_fname)

        return result
