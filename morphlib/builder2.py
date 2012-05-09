# Copyright (C) 2012  Codethink Limited
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import json
import logging
import os
import shutil
import time

import morphlib


def ldconfig(ex, rootdir): # pragma: no cover
    '''Run ldconfig for the filesystem below ``rootdir``.

    Essentially, ``rootdir`` specifies the root of a new system.
    Only directories below it are considered.

    ``etc/ld.so.conf`` below ``rootdir`` is assumed to exist and
    be populated by the right directories, and should assume
    the root directory is ``rootdir``. Example: if ``rootdir``
    is ``/tmp/foo``, then ``/tmp/foo/etc/ld.so.conf`` should
    contain ``/lib``, not ``/tmp/foo/lib``.
    
    The ldconfig found via ``$PATH`` is used, not the one in ``rootdir``,
    since in bootstrap mode that might not yet exist, the various 
    implementations should be compatible enough.

    '''

    conf = os.path.join(rootdir, 'etc', 'ld.so.conf')
    if os.path.exists(conf):
        logging.debug('Running ldconfig for %s' % rootdir)
        cache = os.path.join(rootdir, 'etc', 'ld.so.cache')
        
        # The following trickery with $PATH is necessary during the Baserock
        # bootstrap build: we are not guaranteed that PATH contains the
        # directory (/sbin conventionally) that ldconfig is in. Then again,
        # it might, and if so, we don't want to hardware a particular
        # location. So we add the possible locations to the end of $PATH
        # and restore that aftewards.
        old_path = ex.env['PATH']
        ex.env['PATH'] = '%s:/sbin:/usr/sbin:/usr/local/sbin' % old_path
        ex.runv(['ldconfig', '-r', rootdir])
        ex.env['PATH'] = old_path
    else:
        logging.debug('No %s, not running ldconfig' % conf)


class BuilderBase(object):

    '''Base class for building artifacts.'''

    def __init__(self, staging_area, local_artifact_cache,
                 remote_artifact_cache, artifact, repo_cache,
                 build_env, max_jobs, setup_proc):
        self.staging_area = staging_area
        self.local_artifact_cache = local_artifact_cache
        self.remote_artifact_cache = remote_artifact_cache
        self.artifact = artifact
        self.repo_cache = repo_cache
        self.build_env = build_env
        self.max_jobs = max_jobs
        self.build_watch = morphlib.stopwatch.Stopwatch()
        self.setup_proc = setup_proc

    def save_build_times(self):
        '''Write the times captured by the stopwatch'''
        meta = {
            'build-times': {}
        }
        for stage in self.build_watch.ticks.iterkeys():
            meta['build-times'][stage] = {
                'start': '%s' % self.build_watch.start_time(stage),
                'stop': '%s' % self.build_watch.stop_time(stage),
                'delta': '%.4f' % self.build_watch.start_stop_seconds(stage)
            }

        logging.debug('Writing metadata to the cache')
        with self.local_artifact_cache.put_source_metadata(
                self.artifact.source, self.artifact.cache_key,
                'meta') as f:
            json.dump(meta, f, indent=4, sort_keys=True)
            f.write('\n')
    
    def create_metadata(self, artifact_name):
        '''Create metadata to artifact to allow it to be reproduced later.
        
        The metadata is represented as a dict, which later on will be
        written out as a JSON file.
        
        '''
        
        assert isinstance(self.artifact.source.repo, 
                          morphlib.cachedrepo.CachedRepo)
        meta = {
            'artifact-name': artifact_name,
            'source-name': self.artifact.source.morphology['name'],
            'kind': self.artifact.source.morphology['kind'],
            'description': self.artifact.source.morphology['description'],
            'repo': self.artifact.source.repo.url,
            'original_ref': self.artifact.source.original_ref,
            'sha1': self.artifact.source.sha1,
            'morphology': self.artifact.source.filename,
            'cache-key': self.artifact.cache_key,
            'cache-id': self.artifact.cache_id,
        }
        
        return meta

    # Wrapper around open() to allow it to be overridden by unit tests.
    def _open(self, filename, mode): # pragma: no cover
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        return open(filename, mode)

    def write_metadata(self, instdir, artifact_name):
        '''Write the metadata for an artifact.
        
        The file will be located under the ``baserock`` directory under
        instdir, named after ``cache_key`` with ``.meta`` as the suffix.
        It will be in JSON format.
        
        '''
        
        meta = self.create_metadata(artifact_name)

        basename = '%s.meta' % artifact_name
        filename = os.path.join(instdir, 'baserock', basename)

        # Unit tests use StringIO, which in Python 2.6 isn't usable with
        # the "with" statement. So we don't do it with "with".
        f = self._open(filename, 'w')
        f.write(json.dumps(meta, indent=4, sort_keys=True))
        f.close()
        
    def new_artifact(self, artifact_name):
        '''Return an Artifact object for something built from our source.'''
        a = morphlib.artifact.Artifact(self.artifact.source, artifact_name)
        a.cache_key = self.artifact.cache_key
        return a
        
    def runcmd(self, *args, **kwargs):
        kwargs['env'] = self.build_env.env
        return self.staging_area.runcmd(*args, **kwargs)


class ChunkBuilder(BuilderBase):

    '''Build chunk artifacts.'''
    
    def get_commands(self, which, morphology, build_system):
        '''Return the commands to run from a morphology or the build system.'''
        if morphology[which] is None:
            attr = '_'.join(which.split('-'))
            return getattr(build_system, attr)
        else:
            return morphology[which]

    def build_and_cache(self): # pragma: no cover
        with self.build_watch('overall-build'):
            mounted = self.mount_proc()
            try:
                builddir = self.staging_area.builddir(self.artifact.source)
                self.get_sources(builddir)
                destdir = self.staging_area.destdir(self.artifact.source)
                self.run_commands(builddir, destdir)
            except:
                self.umount_proc(mounted)
                raise
            self.umount_proc(mounted)
            self.assemble_chunk_artifacts(destdir)

        self.save_build_times()

    def mount_proc(self): # pragma: no cover
        logging.debug('Mounting /proc in staging area')
        path = os.path.join(self.staging_area.dirname, 'proc')
        if os.path.exists(path) and self.setup_proc:
            ex = morphlib.execute.Execute('.', logging.debug)
            ex.runv(['mount', '-t', 'proc', 'none', path])
            return path
        else:
            logging.debug('Not mounting /proc after all, %s does not exist' %
                            path)
            return None

    def umount_proc(self, mounted): # pragma: no cover
        if (mounted and self.setup_proc and mounted and 
            os.path.exists(os.path.join(mounted, 'self'))):
            logging.error('Unmounting /proc in staging area: %s' % mounted)
            ex = morphlib.execute.Execute('.', logging.debug)
            ex.runv(['umount', mounted])

    def get_sources(self, srcdir): # pragma: no cover
        '''Get sources from git to a source directory, for building.'''

        cache_dir = os.path.dirname(self.artifact.source.repo.path)

        def extract_repo(path, sha1, destdir):
            logging.debug('Extracting %s into %s' % (path, destdir))
            if not os.path.exists(destdir):
                os.mkdir(destdir)
            morphlib.git.copy_repository(path, destdir, logging.debug)
            morphlib.git.checkout_ref(destdir, sha1, logging.debug)
            morphlib.git.reset_workdir(destdir, logging.debug)
            submodules = morphlib.git.Submodules(path, sha1)
            try:
                submodules.load()
            except morphlib.git.NoModulesFileError:
                return []
            else:
                tuples = []
                for sub in submodules:
                    cached_repo = self.repo_cache.get_repo(sub.url)
                    sub_dir = os.path.join(destdir, sub.path)
                    tuples.append((cached_repo.path, sub.commit, sub_dir))
                return tuples

        s = self.artifact.source
        todo = [(s.repo.path, s.sha1, srcdir)]
        while todo:
            path, sha1, srcdir = todo.pop()
            todo += extract_repo(path, sha1, srcdir)
        self.set_mtime_recursively(srcdir)

    def set_mtime_recursively(self, root): # pragma: no cover
        '''Set the mtime for every file in a directory tree to the same.
        
        We do this because git checkout does not set the mtime to anything,
        and some projects (binutils, gperf for example) include formatted
        documentation and try to randomly build things or not because of
        the timestamps. This should help us get more reliable  builds.
        
        '''
        
        now = time.time()
        for dirname, subdirs, basenames in os.walk(root, topdown=False):
            for basename in basenames:
                pathname = os.path.join(dirname, basename)
                # we need the following check to ignore broken symlinks
                if os.path.exists(pathname):
                    os.utime(pathname, (now, now))
            os.utime(dirname, (now, now))


    def run_commands(self, builddir, destdir): # pragma: no cover
        m = self.artifact.source.morphology
        bs = morphlib.buildsystem.lookup_build_system(m['build-system'])

        relative_builddir = self.staging_area.relative(builddir)
        relative_destdir = self.staging_area.relative(destdir)
        self.build_env.env['DESTDIR'] = relative_destdir

        steps = [('configure', False), 
                 ('build', True),
                 ('test', False),
                 ('install', False)]
        for step, in_parallel in steps:
            with self.build_watch(step):
                cmds = self.get_commands('%s-commands' % step, m, bs)
                for cmd in cmds:
                    if in_parallel:
                        max_jobs = self.artifact.source.morphology['max-jobs']
                        if max_jobs is None:
                            max_jobs = self.max_jobs
                        self.build_env.env['MAKEFLAGS'] = '-j%s' % max_jobs
                    else:
                        self.build_env.env['MAKEFLAGS'] = '-j1'
                    self.runcmd(['sh', '-c', cmd], cwd=relative_builddir)

    def assemble_chunk_artifacts(self, destdir): # pragma: no cover
        with self.build_watch('create-chunks'):
            ex = None # create_chunk doesn't actually use this
            specs = self.artifact.source.morphology['chunks']
            if len(specs) == 0:
                specs = {
                    self.artifact.source.morphology['name']: ['.'],
                }
            for artifact_name in specs:
                self.write_metadata(destdir, artifact_name)
                patterns = specs[artifact_name]
                patterns += [r'baserock/%s\.' % artifact_name]
    
                artifact = self.new_artifact(artifact_name)
                with self.local_artifact_cache.put(artifact) as f:
                    logging.debug('assembling chunk %s' % artifact_name)
                    logging.debug('assembling into %s' % f.name)
                    morphlib.bins.create_chunk(destdir, f, patterns, ex)
    
            files = os.listdir(destdir)
            if files:
                raise Exception('DESTDIR %s is not empty: %s' %
                                (destdir, files))


class StratumBuilder(BuilderBase):

    '''Build stratum artifacts.'''

    def build_and_cache(self): # pragma: no cover
        with self.build_watch('overall-build'):
            destdir = self.staging_area.destdir(self.artifact.source)
    
            constituents = [dependency
                            for dependency in self.artifact.dependencies
                            if dependency.source.morphology['kind'] == 'chunk']
            with self.build_watch('unpack-chunks'):
                for chunk_artifact in constituents:
                    # download the chunk artifact if necessary
                    if not self.local_artifact_cache.has(chunk_artifact):
                        source = self.remote_artifact_cache.get(chunk_artifact)
                        target = self.local_artifact_cache.put(chunk_artifact)
                        shutil.copyfileobj(source, target)
                        target.close()
                        source.close()
                    # unpack it from the local artifact cache
                    logging.debug('unpacking chunk %s into stratum %s' %
                                  (chunk_artifact.basename(), 
                                   self.artifact.basename()))
                    f = self.local_artifact_cache.get(chunk_artifact)
                    morphlib.bins.unpack_binary_from_file(f, destdir)
                    f.close()

            with self.build_watch('create-binary'):    
                artifact_name = self.artifact.source.morphology['name']
                self.write_metadata(destdir, artifact_name)
                artifact = self.new_artifact(artifact_name)
                with self.local_artifact_cache.put(artifact) as f:
                    morphlib.bins.create_stratum(destdir, f, None)
        self.save_build_times()


class SystemBuilder(BuilderBase): # pragma: no cover

    '''Build system image artifacts.'''

    def build_and_cache(self):
        with self.build_watch('overall-build'):
            logging.debug('SystemBuilder.do_build called')
            self.ex = morphlib.execute.Execute(self.staging_area.tempdir,
                                               logging.debug)
            
            image_name = os.path.join(self.staging_area.tempdir,
                                      '%s.img' % self.artifact.name)
            self._create_image(image_name)
            self._partition_image(image_name)
            self._install_mbr(image_name)
            partition = self._setup_device_mapping(image_name)
    
            mount_point = None
            try:
                self._create_fs(partition)
                mount_point = self.staging_area.destdir(self.artifact.source)
                self._mount(partition, mount_point)
                factory_path = os.path.join(mount_point, 'factory')
                self._create_subvolume(factory_path)
                self._unpack_strata(factory_path)
                self._create_fstab(factory_path)
                self._create_extlinux_config(factory_path)
                self._create_subvolume_snapshot(
                        mount_point, 'factory', 'factory-run')
                factory_run_path = os.path.join(mount_point, 'factory-run')
                self._install_boot_files(factory_run_path, mount_point)
                self._install_extlinux(mount_point)
                self._unmount(mount_point)
            except BaseException, e:
                logging.error('Got error while system image building, '
                                'unmounting and device unmapping')
                self._unmount(mount_point)
                self._undo_device_mapping(image_name)
                raise
    
            self._undo_device_mapping(image_name)
            self._move_image_to_cache(image_name)
        self.save_build_times()

    def _create_image(self, image_name):
        logging.debug('Creating disk image %s' % image_name)
        with self.build_watch('create-image'):
            morphlib.fsutils.create_image(
                self.ex, image_name,
                self.artifact.source.morphology['disk-size'])

    def _partition_image(self, image_name):
        logging.debug('Partitioning disk image %s' % image_name)
        with self.build_watch('partition-image'):
            morphlib.fsutils.partition_image(self.ex, image_name)

    def _install_mbr(self, image_name):
        logging.debug('Installing mbr on disk image %s' % image_name)
        with self.build_watch('install-mbr'):
            morphlib.fsutils.install_mbr(self.ex, image_name)

    def _setup_device_mapping(self, image_name):
        logging.debug('Device mapping partitions in %s' % image_name)
        with self.build_watch('setup-device-mapper'):
            return morphlib.fsutils.setup_device_mapping(self.ex, image_name)

    def _create_fs(self, partition):
        logging.debug('Creating filesystem on %s' % partition)
        with self.build_watch('create-filesystem'):
            morphlib.fsutils.create_fs(self.ex, partition)

    def _mount(self, partition, mount_point):
        logging.debug('Mounting %s on %s' % (partition, mount_point))
        with self.build_watch('mount-filesystem'):
            morphlib.fsutils.mount(self.ex, partition, mount_point)

    def _create_subvolume(self, path):
        logging.debug('Creating subvolume %s' % path)
        with self.build_watch('create-factory-subvolume'):
            self.ex.runv(['btrfs', 'subvolume', 'create', path])

    def _unpack_strata(self, path):
        logging.debug('Unpacking strata to %s' % path)
        with self.build_watch('unpack-strata'):
            for stratum_artifact in self.artifact.dependencies:
                # download the stratum artifact if necessary
                if not self.local_artifact_cache.has(stratum_artifact):
                    source = self.remote_artifact_cache.get(stratum_artifact)
                    target = self.local_artifact_cache.put(stratum_artifact)
                    shutil.copyfileobj(source, target)
                    target.close()
                    source.close()
                # unpack it from the local artifact cache
                f = self.local_artifact_cache.get(stratum_artifact)
                morphlib.bins.unpack_binary_from_file(f, path)
                f.close()
            ldconfig(self.ex, path)

    def _create_fstab(self, path):
        logging.debug('Creating fstab in %s' % path)
        with self.build_watch('create-fstab'):
            fstab = os.path.join(path, 'etc', 'fstab')
            if not os.path.exists(os.path.dirname(fstab)):# FIXME: should exist
                os.makedirs(os.path.dirname(fstab))
            with open(fstab, 'w') as f:
                f.write('proc      /proc proc  defaults          0 0\n')
                f.write('sysfs     /sys  sysfs defaults          0 0\n')
                f.write('/dev/vda1 / btrfs errors=remount-ro 0 1\n')

    def _create_extlinux_config(self, path):
        logging.debug('Creating extlinux.conf in %s' % path)
        with self.build_watch('create-extlinux-config'):
            config = os.path.join(path, 'extlinux.conf')
            with open(config, 'w') as f:
                f.write('default linux\n')
                f.write('timeout 1\n')
                f.write('label linux\n')
                f.write('kernel /boot/vmlinuz\n')
                f.write('append root=/dev/vda1 rootflags=subvol=factory-run '
                                               'init=/lib/systemd/systemd rw\n')
    
    def _create_subvolume_snapshot(self, path, source, target):
        logging.debug('Creating subvolume snapshot %s to %s' % 
                        (source, target))
        with self.build_watch('create-runtime-snapshot'):
            self.ex.runv(['btrfs', 'subvolume', 'snapshot', source, target],
                         cwd=path)

    def _install_boot_files(self, sourcefs, targetfs):
        logging.debug('installing boot files into root volume')
        with self.build_watch('install-boot-files'):
            shutil.copy2(os.path.join(sourcefs, 'extlinux.conf'),
                         os.path.join(targetfs, 'extlinux.conf'))
            os.mkdir(os.path.join(targetfs, 'boot'))
            shutil.copy2(os.path.join(sourcefs, 'boot', 'vmlinuz'),
                         os.path.join(targetfs, 'boot', 'vmlinuz'))
            shutil.copy2(os.path.join(sourcefs, 'boot', 'System.map'),
                         os.path.join(targetfs, 'boot', 'System.map'))

    def _install_extlinux(self, path):
        logging.debug('Installing extlinux to %s' % path)
        with self.build_watch('install-bootloader'):
            self.ex.runv(['extlinux', '--install', path])

            # FIXME this hack seems to be necessary to let extlinux finish
            self.ex.runv(['sync'])
            time.sleep(2)

    def _unmount(self, mount_point):
        logging.debug('Unmounting %s' % mount_point)
        with self.build_watch('unmount-filesystem'):
            if mount_point is not None:
                morphlib.fsutils.unmount(self.ex, mount_point)

    def _undo_device_mapping(self, image_name):
        logging.debug('Undoing device mappings for %s' % image_name)
        with self.build_watch('undo-device-mapper'):
            morphlib.fsutils.undo_device_mapping(self.ex, image_name)

    def _move_image_to_cache(self, image_name):
        logging.debug('Moving image to cache: %s' % image_name)
        # FIXME: Need to create file directly in cache to avoid costly
        # copying here.
        with self.build_watch('cache-image'):
            with self.local_artifact_cache.put(self.artifact) as outf:
                with open(image_name) as inf:
                    while True:
                        data = inf.read(1024**2)
                        if not data:
                            break
                        outf.write(data)


class Builder(object): # pragma: no cover

    '''Helper class to build with the right BuilderBase subclass.'''
    
    classes = {
        'chunk': ChunkBuilder,
        'stratum': StratumBuilder,
        'system': SystemBuilder,
    }

    def __init__(self, staging_area, local_artifact_cache,
                 remote_artifact_cache, repo_cache, build_env, max_jobs):
        self.staging_area = staging_area
        self.local_artifact_cache = local_artifact_cache
        self.remote_artifact_cache = remote_artifact_cache
        self.repo_cache = repo_cache
        self.build_env = build_env
        self.max_jobs = max_jobs
        self.setup_proc = False
        
    def build_and_cache(self, artifact):
        kind = artifact.source.morphology['kind']
        o = self.classes[kind](self.staging_area, self.local_artifact_cache, 
                               self.remote_artifact_cache, artifact,
                               self.repo_cache, self.build_env, 
                               self.max_jobs, self.setup_proc)
        logging.debug('Builder.build: artifact %s with %s' %
                      (artifact.name, repr(o)))
        o.build_and_cache()
        logging.debug('Builder.build: done')

