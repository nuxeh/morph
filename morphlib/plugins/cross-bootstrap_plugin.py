# Copyright (C) 2013-2015  Codethink Limited
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.

import cliapp
import logging
import os.path
import re
import tarfile
import traceback

import morphlib

driver_header = '''#!/bin/sh
echo "Morph native bootstrap script"
echo "Generated by Morph version %s\n"

set -eu

export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/tools/bin:/tools/sbin
export SRCDIR=/src

''' % morphlib.__version__

driver_footer = '''

echo "Complete!"
'''

def escape_source_name(source):
    repo_name = source.repo.original_name
    ref = source.original_ref
    source_name = '%s__%s' % (repo_name, ref)
    return re.sub('[:/]', '_', source_name)

# Most of this is ripped from RootfsTarballBuilder, and should be reconciled
# with it.
class BootstrapSystemBuilder(morphlib.builder.BuilderBase):
    '''Build a bootstrap system tarball
    
       The bootstrap system image contains a minimal cross-compiled toolchain
       and a set of extracted sources for the rest of the system, with shell
       scripts to run the required morphology commands. This allows new
       architectures to be bootstrapped without needing to build Python, Git,
       Perl and all of Morph's other dependencies first.
    '''

    def build_and_cache(self):
        with self.build_watch('overall-build'):
            for system_name, artifact in self.source.artifacts.iteritems():
                handle = self.local_artifact_cache.put(artifact)
                fs_root = self.staging_area.destdir(self.source)
                try:
                    self.unpack_binary_chunks(fs_root)
                    self.unpack_sources(fs_root)
                    self.write_build_script(fs_root)
                    self.create_tarball(handle, fs_root, system_name)
                except BaseException as e:
                    logging.error(traceback.format_exc())
                    self.app.status(msg='Error while building bootstrap image',
                                    error=True)
                    handle.abort()
                    raise

                handle.close()

        self.save_build_times()
        return self.source.artifacts.items()

    def unpack_binary_chunks(self, dest):
        cache = self.local_artifact_cache
        for chunk_source in self.source.cross_sources:
            for chunk_artifact in chunk_source.artifacts.itervalues():
                with cache.get(chunk_artifact) as chunk_file:
                    try:
                        morphlib.bins.unpack_binary_from_file(chunk_file, dest)
                    except BaseException as e:
                        self.app.status(
                            msg='Error unpacking binary chunk %(name)s',
                            name=chunk_artifact.name,
                            error=True)
                        raise

    def unpack_sources(self, path):
        # Multiple chunks sources may be built from the same repo ('linux'
        # and 'linux-api-headers' are a good example), so we check out the
        # sources once per repository.
        #
        # It might be neater to build these as "source artifacts" individually,
        # but that would waste huge amounts of space in the artifact cache.
        for s in self.source.native_sources:
            escaped_source = escape_source_name(s)
            source_dir = os.path.join(path, 'src', escaped_source)
            if not os.path.exists(source_dir):
                os.makedirs(source_dir)
                morphlib.builder.extract_sources(
                    self.app, self.repo_cache, s.repo, s.sha1, source_dir)

            name = s.name
            chunk_script = os.path.join(path, 'src', 'build-%s' % name)
            with morphlib.savefile.SaveFile(chunk_script, 'w') as f:
                self.write_chunk_build_script(s, f)
            os.chmod(chunk_script, 0o777)

    def write_build_script(self, path):
        '''Output a script to run build on the bootstrap target'''

        driver_script = os.path.join(path, 'native-bootstrap')
        with morphlib.savefile.SaveFile(driver_script, 'w') as f:
            f.write(driver_header)

            f.write('echo Setting up build environment...\n')
            for k,v in self.staging_area.env.iteritems():
                if k != 'PATH':
                    f.write('export %s="%s"\n' % (k, v))

            for s in self.source.native_sources:
                name = s.name
                f.write('\necho Building %s\n' % name)
                f.write('if [ -d /%s.inst/%s.build ]; then\n'
                        % (name, name))
                f.write('  rm -rf /%s.inst\n' % name)
                f.write('fi\n')
                f.write('if [ ! -d /%s.inst ]; then\n' % name)
                f.write('  mkdir /%s.inst\n' % name)
                f.write('  env DESTDIR=/%s.inst $SRCDIR/build-%s\n'
                        % (name, name))
                f.write('  echo Installing %s\n' % name)
                f.write('  (cd /%s.inst; find . | cpio -umdp /)\n' % name)
                f.write('  if [ -e /sbin/ldconfig ]; '
                        'then /sbin/ldconfig; fi\n')
                f.write('fi\n')

            f.write(driver_footer)
        os.chmod(driver_script, 0o777)

    def write_chunk_build_script(self, source, f):
        m = source.morphology
        f.write('#!/bin/sh\n')
        f.write('# Build script generated by morph\n')
        f.write('set -e\n')
        f.write('chunk_name=%s\n' % m['name'])

        repo = escape_source_name(source)
        f.write('cp -a $SRCDIR/%s $DESTDIR/$chunk_name.build\n' % repo)
        f.write('cd $DESTDIR/$chunk_name.build\n')
        f.write('export PREFIX=%s\n' % source.prefix)

        bs = morphlib.buildsystem.lookup_build_system(m['build-system'])

        # FIXME: merge some of this with Morphology
        steps = [
            ('pre-configure', False),
            ('configure', False),
            ('post-configure', False),
            ('pre-build', True),
            ('build', True),
            ('post-build', True),
            ('pre-test', False),
            ('test', False),
            ('post-test', False),
            ('pre-install', False),
            ('install', False),
            ('post-install', False),
        ]

        for step, in_parallel in steps:
            key = '%s-commands' % step
            cmds = m[key]
            for cmd in cmds:
                f.write('(')
                if in_parallel:
                    max_jobs = m['max-jobs']
                    if max_jobs is None:
                        max_jobs = self.max_jobs
                    f.write('export MAKEFLAGS=-j%s; ' % max_jobs)
                f.write('set -e; %s) || exit 1\n' % cmd)

        f.write('rm -Rf $DESTDIR/$chunk_name.build')

    def create_tarball(self, handle, fs_root, system_name):
        unslashy_root = fs_root[1:]
        def uproot_info(info):
            info.name = os.path.relpath(info.name, unslashy_root)
            if info.islnk():
                info.linkname = os.path.relpath(info.linkname, unslashy_root)
            return info

        tar = tarfile.TarFile.gzopen(fileobj=handle, mode="w",
                                     compresslevel=1,
                                     name=system_name)
        self.app.status(msg='Constructing tarball of root filesystem',
                        chatty=True)
        tar.add(fs_root, recursive=True, filter=uproot_info)
        tar.close()


class CrossBootstrapPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('cross-bootstrap',
                                self.cross_bootstrap,
                                arg_synopsis='TARGET REPO REF SYSTEM-MORPH')

    def disable(self):
        pass

    def cross_bootstrap(self, args):
        '''Cross-bootstrap a system from a different architecture.'''

        # A brief overview of this process: the goal is to native build as much
        # of the system as possible because that's easier, but in order to do
        # so we need at least 'build-essential'. 'morph cross-bootstrap' will
        # cross-build any bootstrap-mode chunks in the given system and
        # will then prepare a large rootfs tarball which, when booted, will
        # build the rest of the chunks in the system using the cross-built
        # build-essential.
        #
        # This approach saves us from having to run Morph, Git, Python, Perl,
        # or anything else complex and difficult to cross-build on the target
        # until it is bootstrapped. The user of this command needs to provide
        # a kernel and handle booting the system themselves (the generated
        # tarball contains a /bin/sh that can be used as 'init'.
        #
        # This function is a variant of the BuildCommand() class in morphlib.

        # To do: make it work on a system branch instead of repo/ref/morph
        # triplet.

        if len(args) < 4:
            raise cliapp.AppException(
                'cross-bootstrap requires 4 arguments: target archicture, and '
                'repo, ref and and name of the system morphology')

        arch = args[0]
        root_repo, ref, system_name = args[1:4]

        if arch not in morphlib.valid_archs:
            raise morphlib.Error('Unsupported architecture "%s"' % arch)

        # Get system artifact

        build_env = morphlib.buildenvironment.BuildEnvironment(
            self.app.settings, arch)
        build_command = morphlib.buildcommand.BuildCommand(self.app, build_env)

        morph_name = morphlib.util.sanitise_morphology_path(system_name)
        srcpool = build_command.create_source_pool(
            root_repo, ref, [morph_name])

        # FIXME: this is a quick fix in order to get it working for
        # Baserock 13 release, it is not a reasonable fix
        def validate(self, root_artifact):
            root_arch = root_artifact.source.morphology['arch']
            target_arch = arch
            if root_arch != target_arch:
                raise morphlib.Error(
                    'Target architecture is %s '
                    'but the system architecture is %s'
                    % (target_arch, root_arch))

        morphlib.buildcommand.BuildCommand._validate_architecture = validate

        system_artifact = build_command.resolve_artifacts(srcpool)

        # Calculate build order
        # This is basically a hacked version of BuildCommand.build_in_order()
        sources = build_command.get_ordered_sources(system_artifact.walk())
        cross_sources = []
        native_sources = []
        for s in sources:
            if s.morphology['kind'] == 'chunk':
                if s.build_mode == 'bootstrap':
                    cross_sources.append(s)
                else:
                    native_sources.append(s)

        if len(cross_sources) == 0:
            raise morphlib.Error(
                'Nothing to cross-compile. Only chunks built in \'bootstrap\' '
                'mode can be cross-compiled.')

        for s in cross_sources:
            build_command.cache_or_build_source(s, build_env)

        for s in native_sources:
            build_command.fetch_sources(s)

        # Install those to the output tarball ...
        self.app.status(msg='Building final bootstrap system image')
        system_artifact.source.cross_sources = cross_sources
        system_artifact.source.native_sources = native_sources
        staging_area = build_command.create_staging_area(
            build_env, use_chroot=False)
        builder = BootstrapSystemBuilder(
            self.app, staging_area, build_command.lac, build_command.rac,
            system_artifact.source, build_command.lrc, 1, False)
        builder.build_and_cache()

        self.app.status(
            msg='Bootstrap tarball for %(name)s is cached at %(cachepath)s',
            name=system_artifact.name,
            cachepath=build_command.lac.artifact_filename(system_artifact))
