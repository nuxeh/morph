# Copyright (C) 2012-2016  Codethink Limited
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


import json
import logging
import os
from os.path import relpath
import shutil
import stat
import tarfile
import time
import traceback
import subprocess
import tempfile
import warnings
import pipes

import cliapp

import morphlib
from morphlib.artifactcachereference import ArtifactCacheReference
import morphlib.gitversion

SYSTEM_INTEGRATION_PATH = os.path.join('baserock', 'system-integration')

def extract_sources(app, repo_cache, repo, sha1, srcdir): #pragma: no cover
    '''Get sources from git to a source directory, including submodules'''

    def extract_repo(repo, sha1, destdir):
        app.status(msg='Extracting %(source)s into %(target)s',
                   source=repo.original_name,
                   target=destdir)

        morphlib.gitdir.checkout_from_cached_repo(repo, sha1, destdir)
        morphlib.git.reset_workdir(app.runcmd, destdir)
        submodules = morphlib.git.Submodules(repo.dirname, sha1, app.runcmd)
        try:
            submodules.load()
        except morphlib.git.NoModulesFileError:
            return []
        else:
            tuples = []
            for sub in submodules:
                cached_repo = repo_cache.get_updated_repo(sub.url, sub.commit)
                sub_dir = os.path.join(destdir, sub.path)
                tuples.append((cached_repo, sub.commit, sub_dir))
            return tuples

    todo = [(repo, sha1, srcdir)]
    while todo:
        repo, sha1, srcdir = todo.pop()
        todo += extract_repo(repo, sha1, srcdir)
    set_mtime_recursively(srcdir)

def set_mtime_recursively(root):  # pragma: no cover
    '''Set the mtime for every file in a directory tree to the same.

    We do this because git checkout does not set the mtime to anything,
    and some projects (binutils, gperf for example) include formatted
    documentation and try to randomly build things or not because of
    the timestamps. This should help us get more reliable  builds.

    '''

    now = time.time()
    for dirname, subdirs, basenames in os.walk(root.encode("utf-8"),
                                               topdown=False):
        for basename in basenames:
            pathname = os.path.join(dirname, basename)
            # we need the following check to ignore broken symlinks
            if os.path.exists(pathname):
                os.utime(pathname, (now, now))
        os.utime(dirname, (now, now))

def ldconfig(app, rootdir):  # pragma: no cover
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
        app.status(msg="Running ldconfig for %(rootdir)s",
                   rootdir=rootdir, chatty=True)
        cache = os.path.join(rootdir, 'etc', 'ld.so.cache')

        # The following trickery with $PATH is necessary during the Baserock
        # bootstrap build: we are not guaranteed that PATH contains the
        # directory (/sbin conventionally) that ldconfig is in. Then again,
        # it might, and if so, we don't want to hardware a particular
        # location. So we add the possible locations to the end of $PATH
        env = dict(os.environ)
        old_path = env['PATH']
        env['PATH'] = '%s:/sbin:/usr/sbin:/usr/local/sbin' % old_path
        app.runcmd(['ldconfig', '-r', rootdir], env=env)
    else:
        app.status(msg="No %(conf)s, not running ldconfig",
                   conf=conf, chatty=True)


def download_depends(constituents, lac, rac, metadatas=None):
    for constituent in constituents:
        if not lac.has(constituent):
            source = rac.get(constituent)
            target = lac.put(constituent)
            shutil.copyfileobj(source, target)
            target.close()
            source.close()
        if metadatas is not None:
            for metadata in metadatas:
                if not lac.has_artifact_metadata(constituent, metadata):
                    if rac.has_artifact_metadata(constituent, metadata):
                        src = rac.get_artifact_metadata(constituent, metadata)
                        dst = lac.put_artifact_metadata(constituent, metadata)
                        shutil.copyfileobj(src, dst)
                        dst.close()
                        src.close()


class BuilderBase(object):

    '''Base class for building artifacts.'''

    def __init__(self, app, staging_area, local_artifact_cache,
                 remote_artifact_cache, source, repo_cache, max_jobs,
                 setup_mounts):
        self.app = app
        self.staging_area = staging_area
        self.local_artifact_cache = local_artifact_cache
        self.remote_artifact_cache = remote_artifact_cache
        self.source = source
        self.repo_cache = repo_cache
        self.max_jobs = max_jobs
        self.build_watch = morphlib.stopwatch.Stopwatch()
        self.setup_mounts = setup_mounts

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
                self.source, self.source.cache_key,
                'meta') as f:
            json.dump(meta, f, indent=4, sort_keys=True,
                      encoding='unicode-escape')
            f.write('\n')

    def create_metadata(self, artifact_name, contents=[]): # pragma: no cover
        '''Create metadata to artifact to allow it to be reproduced later.

        The metadata is represented as a dict, which later on will be
        written out as a JSON file.

        '''

        assert isinstance(self.source.repo,
                          morphlib.repocache.CachedRepo)
        meta = {
            'artifact-name': artifact_name,
            'source-name': self.source.name,
            'kind': self.source.morphology['kind'],
            'description': self.source.morphology['description'],
            'repo': self.source.repo.url,
            'repo-alias': self.source.repo_name,
            'original_ref': self.source.original_ref,
            'sha1': self.source.sha1,
            'morphology': self.source.filename,
            'cache-key': self.source.cache_key,
            'cache-id': self.source.cache_id,
            'morph-version': {
                'ref': morphlib.gitversion.ref,
                'tree': morphlib.gitversion.tree,
                'commit': morphlib.gitversion.commit,
                'version': morphlib.gitversion.version,
            },
            'contents': contents,
        }

        return meta

    # Wrapper around open() to allow it to be overridden by unit tests.
    def _open(self, filename, mode):  # pragma: no cover
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        return open(filename, mode)

    def write_metadata(self, instdir, artifact_name,
                       contents=[]): # pragma: no cover
        '''Write the metadata for an artifact.

        The file will be located under the ``baserock`` directory under
        instdir, named after ``cache_key`` with ``.meta`` as the suffix.
        It will be in JSON format.

        '''

        meta = self.create_metadata(artifact_name, contents)

        basename = '%s.meta' % artifact_name
        filename = os.path.join(instdir, 'baserock', basename)

        # Unit tests use StringIO, which in Python 2.6 isn't usable with
        # the "with" statement. So we don't do it with "with".
        f = self._open(filename, 'w')
        json.dump(meta, f, indent=4, sort_keys=True, encoding='unicode-escape')
        f.close()

    def runcmd(self, *args, **kwargs):
        return self.staging_area.runcmd(*args, **kwargs)

class ChunkBuilder(BuilderBase):

    '''Build chunk artifacts.'''

    def create_devices(self, destdir): # pragma: no cover
        '''Creates device nodes if the morphology specifies them'''
        morphology = self.source.morphology
        perms_mask = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
        if 'devices' in morphology and morphology['devices'] is not None:
            for dev in morphology['devices']:
                destfile = os.path.join(destdir, './' + dev['filename'])
                mode = int(dev['permissions'], 8) & perms_mask
                if dev['type'] == 'c':
                    mode = mode | stat.S_IFCHR
                elif dev['type'] == 'b':
                    mode = mode | stat.S_IFBLK
                else:
                    raise IOError('Cannot create device node %s,'
                                  'unrecognized device type "%s"'
                                  % (destfile, dev['type']))
                self.app.status(msg="Creating device node %s"
                                    % destfile)
                os.mknod(destfile, mode,
                         os.makedev(dev['major'], dev['minor']))
                os.chown(destfile, dev['uid'], dev['gid'])

    def build_and_cache(self):  # pragma: no cover
        with self.build_watch('overall-build'):

            builddir = self.staging_area.real_builddir()
            destdir = self.staging_area.real_destdir()

            stdout = (self.app.output
                if self.app.settings['build-log-on-stdout'] else None)

            cache = self.local_artifact_cache
            logpath = cache.get_source_metadata_filename(
                self.source, self.source.cache_key, 'build-log')

            _, temppath = tempfile.mkstemp(dir=os.path.dirname(logpath))

            try:
                self.get_sources(builddir)
                self.run_commands(temppath, stdout)
                self.create_devices(destdir)

                os.rename(temppath, logpath)
            except BaseException as e:
                logging.error('Caught exception: %s' % str(e))
                logging.info('Cleaning up staging area')
                if os.path.isfile(temppath):
                    with open(temppath) as f:
                        for line in f:
                            logging.error('BUILD OUTPUT: %s' %
                                          line.rstrip('\n'))

                    os.rename(temppath, logpath)
                else:
                    logging.error("Couldn't find build log at %s", temppath)
                raise

            built_artifacts = self.assemble_chunk_artifacts(destdir)

        self.save_build_times()
        return built_artifacts


    def run_commands(self, logfilepath, stdout=None):  # pragma: no cover
        m = self.source.morphology

        relative_builddir = self.staging_area.relative_builddir()
        relative_destdir = self.staging_area.relative_destdir()
        ccache_dir = self.staging_area.ccache_dir()

        extra_env = { 'DESTDIR': relative_destdir }

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
            ('pre-strip', False),
            ('strip', False),
            ('post-strip', False),
        ]
        for step, in_parallel in steps:
            with self.build_watch(step):
                key = '%s-commands' % step
                cmds = m.get(key)
                if not cmds:
                    continue

                with open(logfilepath, 'a') as log:
                    self.app.status(msg='Running %(key)s', key=key)
                    self.app.status(msg='La La')
                    log.write('### %s ###\n' % key.upper())
                    self.app.status(msg='La La 2')

                for cmd in cmds:
                    if cmd is False: cmd = "false"
                    elif cmd is True: cmd = "true"

                    if in_parallel:
                        max_jobs = self.source.morphology['max-jobs']
                        if max_jobs is None:
                            max_jobs = self.max_jobs
                        extra_env['MAKEFLAGS'] = '-j%s' % max_jobs
                    else:
                        extra_env['MAKEFLAGS'] = '-j1'

                    # flushing is needed because writes from python and
                    # writes from being the output in Popen have different
                    # buffers, but flush handles both
                    if stdout:
                        stdout.flush()

                    with open(os.devnull) as devnull:
                        self.app.status(msg='CMD: %s' % cmd)
                        exit_code = self.runcmd(['echo', 'hello!'])
                        self.app.status(msg='exit code: %s' % exit_code)
                        exit_code = self.runcmd(['sh', '-x', '-c', cmd],
                                                extra_env=extra_env,
                                                cwd=relative_builddir,
                                                stdin=devnull,
                                                stdout=stdout or
                                                       subprocess.PIPE,
                                                stderr=subprocess.STDOUT,
                                                logfile=logfilepath,
                                                ccache_dir=ccache_dir)
                    self.app.status(msg='CMD done')


                    if stdout:
                        stdout.flush()

                    if exit_code != 0:
                        if not stdout:
                            with open(logfilepath, 'r') as log:
                                shutil.copyfileobj(log, self.app.output)
                            self.app.output.write("\n")
                            shutil.copyfile(
                                logfilepath,
                                self.staging_area.dirname + '.log')
                        raise cliapp.AppException(
                            "In staging area %s: %s failed (exit_code=%s)" %
                            (self.staging_area.dirname, step, exit_code))

    def write_system_integration_commands(self, destdir,
            integration_commands, artifact_name): # pragma: no cover

        rel_path = SYSTEM_INTEGRATION_PATH
        dest_path = os.path.join(destdir, SYSTEM_INTEGRATION_PATH)

        scripts_created = []

        if not os.path.exists(dest_path):
            os.makedirs(dest_path)

        if artifact_name in integration_commands:
            prefixes_per_artifact = integration_commands[artifact_name]
            for prefix, commands in prefixes_per_artifact.iteritems():
                for index, script in enumerate(commands):
                    script_name = "%s-%s-%04d" % (prefix,
                                                  artifact_name,
                                                  index)
                    script_path = os.path.join(dest_path, script_name)

                    with morphlib.savefile.SaveFile(script_path, 'w') as f:
                        f.write("#!/bin/sh\nset -xeu\n")
                        f.write(script)
                    os.chmod(script_path, 0o555)

                    rel_script_path = os.path.join(SYSTEM_INTEGRATION_PATH,
                                                   script_name)
                    scripts_created += [rel_script_path]

        return scripts_created

    def assemble_chunk_artifacts(self, destdir):  # pragma: no cover
        built_artifacts = []
        filenames = []
        source = self.source
        split_rules = source.split_rules
        morphology = source.morphology
        sys_tag = 'system-integration'

        def filepaths(destdir):
            for dirname, subdirs, basenames in os.walk(destdir):
                subdirsymlinks = [os.path.join(dirname, x) for x in subdirs
                                  if os.path.islink(os.path.join(dirname, x))]
                filenames = [os.path.join(dirname, x) for x in basenames]
                for relpath in (os.path.relpath(x, destdir) for x in
                                [dirname] + subdirsymlinks + filenames):
                    yield relpath

        with self.build_watch('determine-splits'):
            matches, overlaps, unmatched = \
                split_rules.partition(filepaths(destdir))

        system_integration = morphology.get(sys_tag) or {}

        for artifact in system_integration.keys():
            if artifact not in source.artifacts:
                warnings.warn(
                    "Chunk %s has system-integration commands for "
                    "non-existent artifact %s." % (source.name, artifact))

        with self.build_watch('create-chunks'):
            for chunk_artifact_name, chunk_artifact \
                in source.artifacts.iteritems():
                file_paths = matches[chunk_artifact_name]
                chunk_artifact = source.artifacts[chunk_artifact_name]

                def all_parents(path):
                    while path != '':
                        yield path
                        path = os.path.dirname(path)

                def parentify(filenames):
                    names = set()
                    for name in filenames:
                        names.update(all_parents(name))
                    return sorted(names)

                extra_files = self.write_system_integration_commands(
                                  destdir, system_integration,
                                  chunk_artifact_name)
                extra_files += ['baserock/%s.meta' % chunk_artifact_name]
                parented_paths = parentify(file_paths + extra_files)

                with self.local_artifact_cache.put(chunk_artifact) as f:
                    self.write_metadata(destdir, chunk_artifact_name,
                                        parented_paths)

                    self.app.status(msg='Creating chunk artifact %(name)s',
                                    name=chunk_artifact_name)
                    morphlib.bins.create_chunk(destdir, f, parented_paths)
                built_artifacts.append(chunk_artifact)

        for dirname, subdirs, files in os.walk(destdir):
            if files:
                raise Exception('DESTDIR %s is not empty: %s' %
                                (destdir, files))
        return built_artifacts

    def get_sources(self, srcdir):  # pragma: no cover
        s = self.source
        extract_sources(self.app, self.repo_cache, s.repo, s.sha1, srcdir)


class StratumBuilder(BuilderBase):
    '''Build stratum artifacts.'''

    def is_constituent(self, artifact):  # pragma: no cover
        '''True if artifact should be included in the stratum artifact'''
        return (artifact.source.morphology['kind'] == 'chunk' and \
                artifact.source.build_mode != 'bootstrap')

    def build_and_cache(self):  # pragma: no cover
        with self.build_watch('overall-build'):
            constituents = [d for d in self.source.dependencies
                            if self.is_constituent(d)]

            # the only reason the StratumBuilder has to download chunks is to
            # check for overlap now that strata are lists of chunks
            with self.build_watch('check-chunks'):
                for a_name, a in self.source.artifacts.iteritems():
                    # download the chunk artifact if necessary
                    download_depends(constituents,
                                     self.local_artifact_cache,
                                     self.remote_artifact_cache)

            with self.build_watch('create-chunk-list'):
                lac = self.local_artifact_cache
                for a_name, a in self.source.artifacts.iteritems():
                    meta = self.create_metadata(
                        a_name,
                        [x.name for x in constituents])
                    with lac.put_artifact_metadata(a, 'meta')  as f:
                        json.dump(meta, f, indent=4, sort_keys=True)
                    with self.local_artifact_cache.put(a) as f:
                        json.dump([c.basename() for c in constituents], f)
        self.save_build_times()
        return self.source.artifacts.values()


class SystemBuilder(BuilderBase):  # pragma: no cover

    '''Build system image artifacts.'''

    def __init__(self, *args, **kwargs):
        BuilderBase.__init__(self, *args, **kwargs)
        self.args = args
        self.kwargs = kwargs

    def build_and_cache(self):
        self.app.status(msg='Building system %(system_name)s',
                        system_name=self.source.name)

        with self.build_watch('overall-build'):
            arch = self.source.morphology['arch']

            for a_name, artifact in self.source.artifacts.iteritems():
                handle = self.local_artifact_cache.put(artifact)

                try:
                    fs_root = self.staging_area.real_destdir()
                    self.unpack_strata(fs_root)
                    self.write_metadata(fs_root, a_name)
                    self.run_system_integration_commands(fs_root)
                    unslashy_root = fs_root[1:]
                    def uproot_info(info):
                        info.name = relpath(info.name, unslashy_root)
                        if info.islnk():
                            info.linkname = relpath(info.linkname,
                                                    unslashy_root)
                        return info
                    tar = tarfile.open(fileobj=handle, mode="w", name=a_name)
                    self.app.status(msg='Constructing tarball of rootfs',
                                    chatty=True)
                    tar.add(fs_root, recursive=True, filter=uproot_info)
                    tar.close()
                except BaseException as e:
                    logging.error(traceback.format_exc())
                    handle.abort()
                    raise
                else:
                    handle.close()

        self.save_build_times()
        return self.source.artifacts.itervalues()

    def load_stratum(self, stratum_artifact):
        '''Load a stratum from the local artifact cache.

        Returns a list of ArtifactCacheReference instances for the chunks
        contained in the stratum.

        '''
        cache = self.local_artifact_cache
        with cache.get(stratum_artifact) as stratum_file:
            try:
                artifact_list = json.load(stratum_file,
                                          encoding='unicode-escape')
            except ValueError as e:
                raise cliapp.AppException(
                    'Corruption detected: %s while loading %s' %
                    (e, cache.artifact_filename(stratum_artifact)))
        return [ArtifactCacheReference(a) for a in artifact_list]

    def unpack_one_stratum(self, stratum_artifact, target):
        '''Unpack a single stratum into a target directory'''

        cache = self.local_artifact_cache
        for chunk in self.load_stratum(stratum_artifact):
            self.app.status(msg='Unpacking chunk %(basename)s',
                            basename=chunk.basename(), chatty=True)
            with cache.get(chunk) as chunk_file:
                morphlib.bins.unpack_binary_from_file(chunk_file, target)

        target_metadata_dir = os.path.join(target, 'baserock')
        if not os.path.exists(target_metadata_dir):
            os.mkdir(target_metadata_dir)

        target_metadata = os.path.join(
                target_metadata_dir, '%s.meta' % stratum_artifact.name)
        with cache.get_artifact_metadata(stratum_artifact, 'meta') as src_meta:
            with morphlib.savefile.SaveFile(target_metadata, 'w') as dst_meta:
                shutil.copyfileobj(src_meta, dst_meta)

    def unpack_strata(self, path):
        '''Unpack strata into a directory.'''

        self.app.status(msg='Unpacking strata to %(path)s',
                        path=path, chatty=True)
        with self.build_watch('unpack-strata'):
            for a_name, a in self.source.artifacts.iteritems():
                # download the stratum artifacts if necessary
                download_depends(self.source.dependencies,
                                 self.local_artifact_cache,
                                 self.remote_artifact_cache,
                                 ('meta',))

                # download the chunk artifacts if necessary
                for stratum_artifact in self.source.dependencies:
                    chunks = self.load_stratum(stratum_artifact)
                    download_depends(chunks,
                                     self.local_artifact_cache,
                                     self.remote_artifact_cache)

                # unpack it from the local artifact cache
                for stratum_artifact in self.source.dependencies:
                    self.unpack_one_stratum(stratum_artifact, path)

            ldconfig(self.app, path)

    def write_metadata(self, instdir, artifact_name):
        BuilderBase.write_metadata(self, instdir, artifact_name)

        # This code is here only for compatibility reasons
        # Use the new install-essential-files configure extension instead
        os_release_file = os.path.join(instdir, 'etc', 'os-release')
        dirname = os.path.dirname(os_release_file)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        with morphlib.savefile.SaveFile(os_release_file, 'w') as f:
            f.write('NAME="Baserock"\n')
            f.write('ID=baserock\n')
            f.write('HOME_URL="http://wiki.baserock.org"\n')
            f.write('SUPPORT_URL="http://wiki.baserock.org/mailinglist"\n')
            f.write('BUG_REPORT_URL="http://wiki.baserock.org/mailinglist"\n')

        os.chmod(os_release_file, 0o644)

    def run_system_integration_commands(self, rootdir):  # pragma: no cover
        ''' Run the system integration commands '''

        sys_integration_dir = os.path.join(rootdir, SYSTEM_INTEGRATION_PATH)
        if not os.path.isdir(sys_integration_dir):
            return

        env = {
            'PATH': '/bin:/usr/bin:/sbin:/usr/sbin'
        }

        self.app.status(msg='Running the system integration commands')

        to_mount = (
            ('dev/shm', 'tmpfs', 'none'),
            ('tmp',     'tmpfs', 'none'),
        )

        for bin in sorted(os.listdir(sys_integration_dir)):
            argv = [os.path.join(SYSTEM_INTEGRATION_PATH, bin)]
            container_config = dict(
                root=rootdir, mounts=to_mount, mount_proc=True)
            cmdline = morphlib.util.containerised_cmdline(
                argv, **container_config)

            logfilepath = os.path.dirname(rootdir) + '.log'
            teecmd = ['tee', '-a', logfilepath]
            exit_code, out, err = self.app.runcmd_unchecked(
                cmdline, teecmd, env=env,
                stderr=subprocess.STDOUT)

            if exit_code != 0:
                logging.debug('Command returned code %i', exit_code)

                chroot_script = os.path.dirname(rootdir) + '.sh'
                shell_command = ['env', '-i', '--']
                for k, v in env.iteritems():
                    shell_command += ["%s=%s" % (k, v)]
                shell_command += [os.path.join(os.sep, 'bin', 'sh')]
                with open(chroot_script, 'w') as f:
                    cmdline = morphlib.util.containerised_cmdline(
                        shell_command, **container_config)
                    f.write(' '.join(map(pipes.quote, cmdline)))

                with open(logfilepath, 'r') as log:
                    shutil.copyfileobj(log, self.app.output)
                    self.app.output.write("\n")
                    log.seek(0)
                    for line in log:
                        logging.error('INTEGRATION OUTPUT: %s' %
                                      line.rstrip('\n'))

                raise cliapp.AppException(
                    "In staging area %s: system integration "
                    "commands failed (exit_code=%s)"
                    % (os.path.dirname(rootdir), exit_code))

class Builder(object):  # pragma: no cover

    '''Helper class to build with the right BuilderBase subclass.'''

    classes = {
        'chunk': ChunkBuilder,
        'stratum': StratumBuilder,
        'system': SystemBuilder,
    }

    def __init__(self, app, staging_area, local_artifact_cache,
                 remote_artifact_cache, repo_cache, max_jobs, setup_mounts):
        self.app = app
        self.staging_area = staging_area
        self.local_artifact_cache = local_artifact_cache
        self.remote_artifact_cache = remote_artifact_cache
        self.repo_cache = repo_cache
        self.max_jobs = max_jobs
        self.setup_mounts = setup_mounts

    def build_and_cache(self, source):
        kind = source.morphology['kind']
        o = self.classes[kind](self.app, self.staging_area,
                               self.local_artifact_cache,
                               self.remote_artifact_cache, source,
                               self.repo_cache, self.max_jobs,
                               self.setup_mounts)
        self.app.status(msg='Builder.build: artifact %s with %s' %
                       (source.name, repr(o)),
                       chatty=True)
        built_artifacts = o.build_and_cache()
        self.app.status(msg='Builder.build: done',
                        chatty=True)
        return built_artifacts
