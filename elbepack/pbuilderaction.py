# ELBE - Debian Based Embedded Rootfilesystem Builder
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2015-2017 Linutronix GmbH

import os
import subprocess
import sys

from elbepack.directories import elbe_exe
from elbepack.filesystem import TmpdirFilesystem
from elbepack.shellhelper import command_out_stderr, system
from elbepack.xmlpreprocess import PreprocessWrapper


def cmd_exists(x):
    return any(os.access(os.path.join(path, x), os.X_OK)
               for path in os.environ['PATH'].split(os.pathsep))

# Create download directory with timestamp,
# if necessary


def ensure_outdir(opt):
    if opt.outdir is None:
        opt.outdir = '..'

    print(f'Saving generated Files to {opt.outdir}')


class PBuilderError(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)


class PBuilderAction:
    actiondict = {}

    @classmethod
    def register(cls, action):
        cls.actiondict[action.tag] = action

    @classmethod
    def print_actions(cls):
        print('available subcommands are:', file=sys.stderr)
        for a in cls.actiondict:
            print(f'   {a}', file=sys.stderr)

    def __new__(cls, node):
        action = cls.actiondict[node]
        return object.__new__(action)

    def __init__(self, node):
        self.node = node

    def execute(self, _opt, _args):
        raise NotImplementedError('execute() not implemented')


class CreateAction(PBuilderAction):

    tag = 'create'

    def __init__(self, node):
        PBuilderAction.__init__(self, node)

    def execute(self, opt, _args):
        crossopt = ''
        if opt.cross:
            crossopt = '--cross'
        if opt.noccache:
            ccacheopt = '--no-ccache'
            ccachesize = ''
        else:
            ccacheopt = '--ccache-size'
            ccachesize = opt.ccachesize

        if opt.xmlfile:
            try:
                with PreprocessWrapper(opt.xmlfile, opt) as ppw:
                    ret, prjdir, err = command_out_stderr(
                        f'{sys.executable} {elbe_exe} control create_project')
                    if ret != 0:
                        print('elbe control create_project failed.',
                              file=sys.stderr)
                        print(err, file=sys.stderr)
                        print('Giving up', file=sys.stderr)
                        sys.exit(152)

                    prjdir = prjdir.strip()
                    ret, _, err = command_out_stderr(
                        f'{sys.executable} {elbe_exe} control set_xml "{prjdir}" "{ppw.preproc}"')

                    if ret != 0:
                        print('elbe control set_xml failed.', file=sys.stderr)
                        print(err, file=sys.stderr)
                        print('Giving up', file=sys.stderr)
                        sys.exit(153)
            except subprocess.CalledProcessError:
                # this is the failure from PreprocessWrapper
                # it already printed the error message from
                # elbe preprocess
                print('Giving up', file=sys.stderr)
                sys.exit(154)

            if opt.writeproject:
                wpf = open(opt.writeproject, 'w')
                wpf.write(prjdir)
                wpf.close()

        elif opt.project:
            prjdir = opt.project
        else:
            print('you need to specify --project option', file=sys.stderr)
            sys.exit(155)

        print('Creating pbuilder')

        try:
            system(f'{sys.executable} {elbe_exe} control '
                   f'build_pbuilder "{prjdir}" {crossopt} {ccacheopt} {ccachesize}')
        except subprocess.CalledProcessError:
            print('elbe control build_pbuilder Failed', file=sys.stderr)
            print('Giving up', file=sys.stderr)
            sys.exit(156)

        try:
            system(f'{sys.executable} {elbe_exe} control wait_busy "{prjdir}"')
        except subprocess.CalledProcessError:
            print('elbe control wait_busy Failed', file=sys.stderr)
            print('Giving up', file=sys.stderr)
            sys.exit(157)

        print('')
        print('Building Pbuilder finished !')
        print('')


PBuilderAction.register(CreateAction)


class UpdateAction(PBuilderAction):

    tag = 'update'

    def __init__(self, node):
        PBuilderAction.__init__(self, node)

    def execute(self, opt, _args):

        if not opt.project:
            print('you need to specify --project option', file=sys.stderr)
            sys.exit(158)

        prjdir = opt.project

        print('Updating pbuilder')

        try:
            system(f'{sys.executable} {elbe_exe} control update_pbuilder "{prjdir}"')
        except subprocess.CalledProcessError:
            print('elbe control update_pbuilder Failed', file=sys.stderr)
            print('Giving up', file=sys.stderr)
            sys.exit(159)

        print('')
        print('Updating Pbuilder finished !')
        print('')


PBuilderAction.register(CreateAction)


class BuildAction(PBuilderAction):

    tag = 'build'

    def __init__(self, node):
        PBuilderAction.__init__(self, node)

    def execute(self, opt, _args):

        crossopt = ''
        if opt.cross:
            crossopt = '--cross'
        tmp = TmpdirFilesystem()

        if opt.xmlfile:
            ret, prjdir, err = command_out_stderr(
                f'{sys.executable} {elbe_exe} control create_project --retries 60 "{opt.xmlfile}"')
            if ret != 0:
                print('elbe control create_project failed.', file=sys.stderr)
                print(err, file=sys.stderr)
                print('Giving up', file=sys.stderr)
                sys.exit(160)

            prjdir = prjdir.strip()

            try:
                system(f'{sys.executable} {elbe_exe} control build_pbuilder "{prjdir}"')
            except subprocess.CalledProcessError:
                print('elbe control build_pbuilder Failed', file=sys.stderr)
                print('Giving up', file=sys.stderr)
                sys.exit(161)

            try:
                system(f'{sys.executable} {elbe_exe} control wait_busy "{prjdir}"')
            except subprocess.CalledProcessError:
                print('elbe control wait_busy Failed', file=sys.stderr)
                print('Giving up', file=sys.stderr)
                sys.exit(162)

            print('')
            print('Building Pbuilder finished !')
            print('')
        elif opt.project:
            prjdir = opt.project
            system(f'{sys.executable} {elbe_exe} control rm_log {prjdir}')
        else:
            print(
                'you need to specify --project or --xmlfile option',
                file=sys.stderr)
            sys.exit(163)

        print('')
        print('Packing Source into tmp archive')
        print('')
        try:
            system(f'tar cfz "{tmp.fname("pdebuild.tar.gz")}" .')
        except subprocess.CalledProcessError:
            print('tar Failed', file=sys.stderr)
            print('Giving up', file=sys.stderr)
            sys.exit(164)

        for of in opt.origfile:
            print('')
            print(f"Pushing orig file '{of}' into pbuilder")
            print('')
            try:
                system(
                    f'{sys.executable} {elbe_exe} control set_orig "{prjdir}" "{of}"')
            except subprocess.CalledProcessError:
                print('elbe control set_orig Failed', file=sys.stderr)
                print('Giving up', file=sys.stderr)
                sys.exit(165)

        print('')
        print('Pushing source into pbuilder')
        print('')

        try:
            system(
                f'{sys.executable} {elbe_exe} control set_pdebuild --cpuset "{opt.cpuset}" '
                f'--profile "{opt.profile}" {crossopt} '
                f'"{prjdir}" "{tmp.fname("pdebuild.tar.gz")}"')
        except subprocess.CalledProcessError:
            print('elbe control set_pdebuild Failed', file=sys.stderr)
            print('Giving up', file=sys.stderr)
            sys.exit(166)
        try:
            system(f'{sys.executable} {elbe_exe} control wait_busy "{prjdir}"')
        except subprocess.CalledProcessError:
            print('elbe control wait_busy Failed', file=sys.stderr)
            print('Giving up', file=sys.stderr)
            sys.exit(167)
        print('')
        print('Pdebuild finished !')
        print('')

        if opt.skip_download:
            print('')
            print('Listing available files:')
            print('')
            try:
                system(
                    f'{sys.executable} {elbe_exe} control --pbuilder-only get_files "{prjdir}"')
            except subprocess.CalledProcessError:
                print('elbe control get_files Failed', file=sys.stderr)
                print('', file=sys.stderr)
                print('dumping logfile', file=sys.stderr)

                try:
                    system(f'{sys.executable} {elbe_exe} control dump_file "{prjdir}" log.txt')
                except subprocess.CalledProcessError:
                    print('elbe control dump_file Failed', file=sys.stderr)
                    print('', file=sys.stderr)
                    print('Giving up', file=sys.stderr)

                sys.exit(168)

            print('')
            print(f"Get Files with: 'elbe control get_file {prjdir} <filename>'")
        else:
            print('')
            print('Getting generated Files')
            print('')

            ensure_outdir(opt)

            try:
                system(
                    f'{sys.executable} {elbe_exe} control --pbuilder-only get_files '
                    f'--output "{opt.outdir}" "{prjdir}"')
            except subprocess.CalledProcessError:
                print('elbe control get_files Failed', file=sys.stderr)
                print('', file=sys.stderr)
                print('dumping logfile', file=sys.stderr)

                try:
                    system(f'{sys.executable} {elbe_exe} control dump_file "{prjdir}" log.txt')
                except subprocess.CalledProcessError:
                    print('elbe control dump_file Failed', file=sys.stderr)
                    print('', file=sys.stderr)
                    print('Giving up', file=sys.stderr)

                sys.exit(169)


PBuilderAction.register(BuildAction)
