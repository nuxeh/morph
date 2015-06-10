# Copyright (C) 2011-2015  Codethink Limited
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


import itertools
import os
import shutil
import logging
import tempfile
import datetime

import morphlib
import distbuild


class MultipleRootArtifactsError(morphlib.Error):

    def __init__(self, artifacts):
        self.msg = ('System build has multiple root artifacts: %r'
                    % [a.name for a in artifacts])
        self.artifacts = artifacts


class BuildCommand(object):

    '''High level logic for building.

    This controls how the whole build process goes. This is a separate
    class to enable easy experimentation of different approaches to
    the various parts of the process.

    '''

    def __init__(self, app, build_env = None):
        self.supports_local_build = True

        self.app = app
        self.lac, self.rac = self.new_artifact_caches()
        self.lrc, self.rrc = self.new_repo_caches()

    def build(self, repo_name, ref, filename, original_ref=None):
        '''Build a given system morphology.'''

        self.app.status(
            msg='Building %(repo_name)s %(ref)s %(filename)s',
            repo_name=repo_name, ref=ref, filename=filename)

        self.app.status(msg='Deciding on task order')
        srcpool = self.create_source_pool(
            repo_name, ref, [filename], original_ref)
        self.validate_sources(srcpool)
        root_artifact = self.resolve_artifacts(srcpool)
        self.build_in_order(root_artifact)

        self.app.status(
            msg='Build of %(repo_name)s %(ref)s %(filename)s ended '
                'successfully',
            repo_name=repo_name, ref=ref, filename=filename)

    def new_artifact_caches(self):
        '''Create interfaces for the build artifact caches.

        This includes creating the directories on disk if they are missing.

        '''
        return morphlib.util.new_artifact_caches(self.app.settings)

    def new_repo_caches(self):
        return morphlib.util.new_repo_caches(self.app)

    def new_build_env(self, arch):
        '''Create a new BuildEnvironment instance.'''
        return morphlib.buildenvironment.BuildEnvironment(self.app.settings,
                                                          arch)

    def create_source_pool(self, repo_name, ref, filenames,
                           original_ref=None):
        '''Find the source objects required for building a the given artifact

        The SourcePool will contain every stratum and chunk dependency of the
        given artifact (which must be a system) but will not take into account
        any Git submodules which are required in the build.

        '''
        self.app.status(msg='Creating source pool', chatty=True)
        srcpool = morphlib.sourceresolver.create_source_pool(
            self.lrc, self.rrc, repo_name, ref, filenames,
            cachedir=self.app.settings['cachedir'],
            original_ref=original_ref,
            update_repos=not self.app.settings['no-git-update'],
            status_cb=self.app.status)
        return srcpool

    def validate_sources(self, srcpool):
        self.app.status(
            msg='Validating cross-morphology references', chatty=True)
        self._validate_cross_morphology_references(srcpool)

        self.app.status(msg='Validating for there being non-bootstrap chunks',
                        chatty=True)
        self._validate_has_non_bootstrap_chunks(srcpool)

    def _validate_root_artifact(self, root_artifact):
        self._validate_root_kind(root_artifact)
        self._validate_architecture(root_artifact)

    @staticmethod
    def _validate_root_kind(root_artifact):
        root_kind = root_artifact.source.morphology['kind']
        if root_kind != 'system':
            raise morphlib.Error(
                'In order to build this %s directly, please give the filename '
                'of the system which contains it, and the name of the %s. '
                'See `morph build --help` for more information.'
                % (root_kind, root_kind))

    def _validate_architecture(self, root_artifact):
        '''Perform the validation between root and target architectures.'''

        root_arch = root_artifact.source.morphology['arch']
        host_arch = morphlib.util.get_host_architecture()

        if root_arch == host_arch:
            return

        # Since the armv8 instruction set is nearly entirely armv7 compatible,
        # and since the incompatibilities are appropriately trapped in the
        # kernel, we can safely run any armv7 toolchain natively on armv8.
        if host_arch == 'armv8l' and root_arch in ('armv7l', 'armv7lhf'):
            return
        if host_arch == 'armv8b' and root_arch in ('armv7b', 'armv7bhf'):
            return

        # Since the armv7 instruction set is nearly entirely armv5 compatible,
        # and since the incompatibilities are appropriately trapped in the
        # kernel, we can safely run any armv5 toolchain natively on armv7.
        if host_arch in ('armv7l', 'armv7lhf') and root_arch in ('armv5l',
                                                    'armv6l', 'armv6lhf'):
            return

        raise morphlib.Error(
            'Are you trying to cross-build? Host architecture is %s but '
            'target is %s' % (host_arch, root_arch))

    @staticmethod
    def _validate_has_non_bootstrap_chunks(srcpool):
        stratum_sources = [src for src in srcpool
                           if src.morphology['kind'] == 'stratum']
        # any will return true for an empty iterable, which will give
        # a false positive when there are no strata.
        # This is an error by itself, but the source of this error can
        # be better diagnosed later, so we abort validating here.
        if not stratum_sources:
            return

        if not any(spec.get('build-mode', 'staging') != 'bootstrap'
                   for src in stratum_sources
                   for spec in src.morphology['chunks']):
            raise morphlib.Error('No non-bootstrap chunks found.')

    def _compute_cache_keys(self, root_artifact):
        arch = root_artifact.source.morphology['arch']
        self.app.status(msg='Creating build environment for %(arch)s',
                        arch=arch, chatty=True)
        build_env = self.new_build_env(arch)

        self.app.status(msg='Computing cache keys', chatty=True)
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        for source in set(a.source for a in root_artifact.walk()):
            source.cache_key = ckc.compute_key(source)
            source.cache_id = ckc.get_cache_id(source)

        root_artifact.build_env = build_env

    def resolve_artifacts(self, srcpool):
        '''Resolve the artifacts that will be built for a set of sources'''

        self.app.status(msg='Creating artifact resolver', chatty=True)
        ar = morphlib.artifactresolver.ArtifactResolver()

        self.app.status(msg='Resolving artifacts', chatty=True)
        root_artifacts = ar.resolve_root_artifacts(srcpool)

        if len(root_artifacts) > 1:
            # Validate root artifacts to give a more useful error message
            for root_artifact in root_artifacts:
                self._validate_root_artifact(root_artifact)
            raise MultipleRootArtifactsError(root_artifacts)

        root_artifact = root_artifacts[0]
        self.app.status(msg='Validating root artifact', chatty=True)
        self._validate_root_artifact(root_artifact)

        self._compute_cache_keys(root_artifact)

        return root_artifact

    def _validate_cross_morphology_references(self, srcpool):
        '''Perform validation across all morphologies involved in the build'''

        stratum_names = {}

        for src in srcpool:
            kind = src.morphology['kind']

            # Verify that chunks pointed to by strata really are chunks, etc.
            method_name = '_validate_cross_refs_for_%s' % kind
            if hasattr(self, method_name):
                logging.debug('Calling %s' % method_name)
                getattr(self, method_name)(src, srcpool)
            else:
                logging.warning('No %s' % method_name)

            # Verify stratum build-depends agree with the system's contents.
            # It is permissible for a stratum to build-depend on a stratum that
            # isn't specified in the target system morphology.
            # Multiple references to the same stratum are permitted. This is
            # handled by the SourcePool deduplicating added Sources.
            # It is forbidden to have two different strata with the same name.
            # Hence if a Stratum is defined in the System, and in a Stratum as
            # a build-dependency, then they must both have the same Repository
            # and Ref specified.
            if src.morphology['kind'] == 'stratum':
                name = src.name
                if name in stratum_names:
                    raise morphlib.Error(
                        "Multiple strata produce a '%s' artifact: %s and %s" %
                        (name, stratum_names[name].filename, src.filename))
                stratum_names[name] = src

    def _validate_cross_refs_for_system(self, src, srcpool):
        self._validate_cross_refs_for_xxx(
            src, srcpool, src.morphology['strata'], 'stratum')

    def _validate_cross_refs_for_stratum(self, src, srcpool):
        self._validate_cross_refs_for_xxx(
            src, srcpool, src.morphology['chunks'], 'chunk')

    def _validate_cross_refs_for_xxx(self, src, srcpool, specs, wanted):
        for spec in specs:
            repo_name = spec.get('repo') or src.repo_name
            ref = spec.get('ref') or src.original_ref
            filename = morphlib.util.sanitise_morphology_path(
                spec.get('morph', spec.get('name')))
            logging.debug(
                'Validating cross ref to %s:%s:%s' %
                    (repo_name, ref, filename))
            for other in srcpool.lookup(repo_name, ref, filename):
                if other.morphology['kind'] != wanted:
                    raise morphlib.Error(
                        '%s %s references %s:%s:%s which is a %s, '
                            'instead of a %s' %
                            (src.morphology['kind'],
                             src.name,
                             repo_name,
                             ref,
                             filename,
                             other.morphology['kind'],
                             wanted))

    @staticmethod
    def get_ordered_sources(artifacts):
        ordered_sources = []
        known_sources = set()
        for artifact in artifacts:
            if artifact.source not in known_sources:
                known_sources.add(artifact.source)
                yield artifact.source

    def build_in_order(self, root_artifact):
        '''Build everything specified in a build order.'''

        self.app.status(msg='Starting build of %(name)s',
                        name=root_artifact.source.name)
        build_env = root_artifact.build_env
        ordered_sources = list(self.get_ordered_sources(root_artifact.walk()))
        old_prefix = self.app.status_prefix
        for i, s in enumerate(ordered_sources):
            self.app.status_prefix = (
                old_prefix + '[Build %(index)d/%(total)d] [%(name)s] ' % {
                    'index': (i+1),
                    'total': len(ordered_sources),
                    'name': s.name,
                })

            self.cache_or_build_source(s, build_env)

        self.app.status_prefix = old_prefix

    def cache_or_build_source(self, source, build_env):
        '''Make artifacts of the built source available in the local cache.

        This can be done by retrieving from a remote artifact cache, or if
        that doesn't work for some reason, by building the source locally.

        '''
        artifacts = source.artifacts.values()
        if self.rac is not None:
            try:
                self.cache_artifacts_locally(artifacts)
            except morphlib.remoteartifactcache.GetError:
                # Error is logged by the RemoteArtifactCache object.
                pass

        if any(not self.lac.has(artifact) for artifact in artifacts):
            self.build_source(source, build_env)

        for a in artifacts:
            self.app.status(msg='%(kind)s %(name)s is cached at %(cachepath)s',
                            kind=source.morphology['kind'], name=a.name,
                            cachepath=self.lac.artifact_filename(a),
                            chatty=(source.morphology['kind'] != "system"))

    def build_source(self, source, build_env):
        '''Build all artifacts for one source.

        All the dependencies are assumed to be built and available
        in either the local or remote cache already.

        '''
        starttime = datetime.datetime.now()
        self.app.status(msg='Building %(kind)s %(name)s',
                        name=source.name,
                        kind=source.morphology['kind'])

        self.fetch_sources(source)
        # TODO: Make an artifact.walk() that takes multiple root artifacts.
        # as this does a walk for every artifact. This was the status
        # quo before build logic was made to work per-source, but we can
        # now do better.
        deps = self.get_recursive_deps(source.artifacts.values())
        self.cache_artifacts_locally(deps)

        use_chroot = False
        setup_mounts = False
        if source.morphology['kind'] == 'chunk':
            build_mode = source.build_mode
            extra_env = {'PREFIX': source.prefix}

            dep_prefix_set = set(a.source.prefix for a in deps
                                 if a.source.morphology['kind'] == 'chunk')
            extra_path = [os.path.join(d, 'bin') for d in dep_prefix_set]

            if build_mode not in ['bootstrap', 'staging', 'test']:
                logging.warning('Unknown build mode %s for chunk %s. '
                                'Defaulting to staging mode.' %
                                (build_mode, artifact.name))
                build_mode = 'staging'

            if build_mode == 'staging':
                use_chroot = True
                setup_mounts = True

            staging_area = self.create_staging_area(build_env,
                                                    use_chroot,
                                                    extra_env=extra_env,
                                                    extra_path=extra_path)
            try:
                self.install_dependencies(staging_area, deps, source)
            except BaseException:
                staging_area.abort()
                raise
        else:
            staging_area = self.create_staging_area(build_env, False)

        self.build_and_cache(staging_area, source, setup_mounts)
        self.remove_staging_area(staging_area)

        td = datetime.datetime.now() - starttime
        hours, remainder = divmod(int(td.total_seconds()), 60*60)
        minutes, seconds = divmod(remainder, 60)
        td_string = "%02d:%02d:%02d" % (hours, minutes, seconds)
        self.app.status(msg="Elapsed time %(duration)s", duration=td_string)

    def get_recursive_deps(self, artifacts):
        deps = set()
        ordered_deps = []
        for artifact in artifacts:
            for dep in artifact.walk():
                if dep not in deps and dep not in artifacts:
                    deps.add(dep)
                    ordered_deps.append(dep)
        return ordered_deps

    def fetch_sources(self, source):
        '''Update the local git repository cache with the sources.'''

        repo_name = source.repo_name
        source.repo = self.lrc.get_updated_repo(repo_name, ref=source.sha1)
        self.lrc.ensure_submodules(source.repo, source.sha1)

    def cache_artifacts_locally(self, artifacts):
        '''Get artifacts missing from local cache from remote cache.'''

        def fetch_files(to_fetch):
            '''Fetch a set of files atomically.

            If an error occurs during the transfer of any files, all downloaded
            data is deleted, to ensure integrity of the local cache.

            '''
            try:
                for remote, local in to_fetch:
                    shutil.copyfileobj(remote, local)
            except BaseException:
                for remote, local in to_fetch:
                    local.abort()
                raise
            else:
                for remote, local in to_fetch:
                    remote.close()
                    local.close()

        for artifact in artifacts:
            # This block should fetch all artifact files in one go, using the
            # 1.0/artifacts method of morph-cache-server. The code to do that
            # needs bringing in from the distbuild.worker_build_connection
            # module into morphlib.remoteartififactcache first.
            to_fetch = []
            if not self.lac.has(artifact):
                to_fetch.append((self.rac.get(artifact),
                                 self.lac.put(artifact)))

            if artifact.source.morphology.needs_artifact_metadata_cached:
                if not self.lac.has_artifact_metadata(artifact, 'meta'):
                    to_fetch.append((
                        self.rac.get_artifact_metadata(artifact, 'meta'),
                        self.lac.put_artifact_metadata(artifact, 'meta')))

            if len(to_fetch) > 0:
                self.app.status(
                    msg='Fetching to local cache: artifact %(name)s',
                    name=artifact.name)
                fetch_files(to_fetch)

    def create_staging_area(self, build_env, use_chroot=True, extra_env={},
                            extra_path=[]):
        '''Create the staging area for building a single artifact.'''

        self.app.status(msg='Creating staging area')
        staging_dir = tempfile.mkdtemp(
            dir=os.path.join(self.app.settings['tempdir'], 'staging'))
        staging_area = morphlib.stagingarea.StagingArea(
            self.app, staging_dir, build_env, use_chroot, extra_env,
            extra_path)
        return staging_area

    def remove_staging_area(self, staging_area):
        '''Remove the staging area.'''

        self.app.status(msg='Removing staging area')
        staging_area.remove()

    # Nasty hack to avoid installing chunks built in 'bootstrap' mode in a
    # different stratum when constructing staging areas.
    # TODO: make nicer by having chunk morphs keep a reference to the
    #       stratum they were in
    def in_same_stratum(self, s1, s2):
        '''Checks whether two chunk sources are from the same stratum.

        In the absence of morphologies tracking where they came from,
        this checks whether both sources are depended on by artifacts
        that belong to sources which have the same morphology.

        '''
        def dependent_stratum_morphs(source):
            dependents = set(itertools.chain.from_iterable(
                a.dependents for a in source.artifacts.itervalues()))
            dependent_strata = set(s for s in dependents
                                   if s.morphology['kind'] == 'stratum')
            return set(s.morphology for s in dependent_strata)
        return dependent_stratum_morphs(s1) == dependent_stratum_morphs(s2)

    def install_dependencies(self, staging_area, artifacts, target_source):
        '''Install chunk artifacts into staging area.

        We only ever care about chunk artifacts as build dependencies,
        so this is not a generic artifact installer into staging area.
        Any non-chunk artifacts are silently ignored.

        All artifacts MUST be in the local artifact cache already.

        '''

        for artifact in artifacts:
            if artifact.source.morphology['kind'] != 'chunk':
                continue
            if artifact.source.build_mode == 'bootstrap':
               if not self.in_same_stratum(artifact.source, target_source):
                    continue
            self.app.status(
                msg='Installing chunk %(chunk_name)s from cache %(cache)s',
                chunk_name=artifact.name,
                cache=artifact.source.cache_key[:7],
                chatty=True)
            handle = self.lac.get(artifact)
            staging_area.install_artifact(handle)

        if target_source.build_mode == 'staging':
            morphlib.builder.ldconfig(self.app.runcmd, staging_area.dirname)

    def build_and_cache(self, staging_area, source, setup_mounts):
        '''Build a source and put its artifacts into the local cache.'''

        self.app.status(msg='Starting actual build: %(name)s '
                            '%(sha1)s',
                        name=source.name, sha1=source.sha1[:7])
        builder = morphlib.builder.Builder(
            self.app, staging_area, self.lac, self.rac, self.lrc,
            self.app.settings['max-jobs'], setup_mounts)
        return builder.build_and_cache(source)

class InitiatorBuildCommand(BuildCommand):

    RECONNECT_INTERVAL = 30 # seconds
    MAX_RETRIES = 1

    def __init__(self, app, addr, port, allow_detach):
        self.app = app
        self.addr = addr
        self.port = port
        self.allow_detach = allow_detach
        self.app.settings['push-build-branches'] = True
        super(InitiatorBuildCommand, self).__init__(app)

    def build(self, repo_name, ref, filename, original_ref=None,
              component_names=[]):
        '''Initiate a distributed build on a controller'''

        distbuild.add_crash_conditions(self.app.settings['crash-condition'])

        if self.addr == '':
            raise morphlib.Error(
                'Need address of controller to run a distbuild')

        self.app.status(msg='Starting distributed build')
        loop = distbuild.MainLoop()
        args = [repo_name, ref, filename, original_ref or ref,
                component_names]
        if self.allow_detach:
            initiator_type = distbuild.InitiatorStart
        else:
            initiator_type = distbuild.Initiator

        cm = distbuild.InitiatorConnectionMachine(self.app,
                                                  self.addr,
                                                  self.port,
                                                  initiator_type,
                                                  [self.app] + args,
                                                  self.RECONNECT_INTERVAL,
                                                  self.MAX_RETRIES)

        loop.add_state_machine(cm)
        try:
            loop.run()
        except KeyboardInterrupt:
            # This will run if the user presses Ctrl+C or sends SIGINT during
            # the build. It won't trigger on SIGTERM, SIGKILL or unhandled
            # Python exceptions.
            logging.info('Received KeyboardInterrupt, aborting.')
            for initiator in loop.state_machines_of_type(distbuild.Initiator):
                connection_id = initiator.connection_id or 'ID'
                self.app.status(msg='Stopping initiator process. To cancel '
                                    'the build use `morph distbuild-cancel '
                                    '%(initiator_connection)s`.',
                                initiator_connection=connection_id)
                initiator.handle_cancel()
