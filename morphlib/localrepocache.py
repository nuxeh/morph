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


import os
import urlparse
import string
import sys
import tempfile

import cliapp
import fs.osfs

import morphlib
from morphlib.util import word_join_list as _word_join_list


# urlparse.urljoin needs to know details of the URL scheme being used.
# It does not know about git:// by default, so we teach it here.
gitscheme = ['git']
urlparse.uses_relative.extend(gitscheme)
urlparse.uses_netloc.extend(gitscheme)
urlparse.uses_params.extend(gitscheme)
urlparse.uses_query.extend(gitscheme)
urlparse.uses_fragment.extend(gitscheme)


def quote_url(url):
    ''' Convert URIs to strings that only contain digits, letters, % and _.

    NOTE: When changing the code of this function, make sure to also apply
    the same to the quote_url() function of lorry. Otherwise the git tarballs
    generated by lorry may no longer be found by morph.

    '''
    valid_chars = string.digits + string.letters + '%_'
    transl = lambda x: x if x in valid_chars else '_'
    return ''.join([transl(x) for x in url])


class NoRemote(morphlib.Error):

    def __init__(self, reponame, errors):
        self.reponame = reponame
        self.errors = errors

    def __str__(self):
        return '\n\t'.join(['Cannot find remote git repository: %s' %
                            self.reponame] + self.errors)


class NotCached(morphlib.Error):
    def __init__(self, reponame):
        self.reponame = reponame

    def __str__(self):  # pragma: no cover
        return 'Repository %s is not cached yet' % self.reponame


class UpdateError(cliapp.AppException):  # pragma: no cover

    def __init__(self, repo):
        cliapp.AppException.__init__(
            self, 'Failed to update cached version of repo %s' % repo)


class CachedRepo(morphlib.gitdir.GitDirectory):
    '''A locally cached Git repository with an origin remote set up.

    On instance of this class represents a locally cached version of a
    remote Git repository. This remote repository is set up as the
    'origin' remote.

    Cached repositories are bare mirrors of the upstream.  Locally created
    branches will be lost the next time the repository updates.

    '''
    def __init__(self, path, original_name, url):
        self.original_name = original_name
        self.url = url
        self.is_mirror = not url.startswith('file://')
        self.already_updated = False

        super(CachedRepo, self).__init__(path)

    def __str__(self):  # pragma: no cover
        return self.url


class LocalRepoCache(object):

    '''Manage locally cached git repositories.

    When we build stuff, we need a local copy of the git repository.
    To avoid having to clone the repositories for every build, we
    maintain a local cache of the repositories: we first clone the
    remote repository to the cache, and then make a local clone from
    the cache to the build environment. This class manages the local
    cached repositories.

    Repositories may be specified either using a full URL, in a form
    understood by git(1), or as a repository name to which a base url
    is prepended. The base urls are given to the class when it is
    created.

    Instead of cloning via a normal 'git clone' directly from the
    git server, we first try to download a tarball from a url, and
    if that works, we unpack the tarball.

    '''

    def __init__(self, app, cachedir, resolver, tarball_base_url=None):
        self._app = app
        self.fs = fs.osfs.OSFS('/')
        self._cachedir = cachedir
        self._resolver = resolver
        if tarball_base_url and not tarball_base_url.endswith('/'):
            tarball_base_url += '/'  # pragma: no cover
        self._tarball_base_url = tarball_base_url
        self._cached_repo_objects = {}

    def _git(self, args, **kwargs):  # pragma: no cover
        '''Execute git command.

        This is a method of its own so that unit tests can easily override
        all use of the external git command.

        '''

        morphlib.git.gitcmd(self._app.runcmd, *args, **kwargs)

    def _fetch(self, url, path):  # pragma: no cover
        '''Fetch contents of url into a file.

        This method is meant to be overridden by unit tests.

        '''
        self._app.status(msg="Trying to fetch %(tarball)s to seed the cache",
                         tarball=url, chatty=True)

        if self._app.settings['verbose']:
            verbosity_flags = []
            kwargs = dict(stderr=sys.stderr)
        else:
            verbosity_flags = ['--quiet']
            kwargs = dict()

        def wget_command():
            return ['wget'] + verbosity_flags + ['-O-', url]

        self._app.runcmd(wget_command(),
                         ['tar', '--no-same-owner', '-xf', '-'],
                         cwd=path, **kwargs)

    def _mkdtemp(self, dirname):  # pragma: no cover
        '''Creates a temporary directory.

        This method is meant to be overridden by unit tests.

        '''
        return tempfile.mkdtemp(dir=dirname)

    def _escape(self, url):
        '''Escape a URL so it can be used as a basename in a file.'''

        # FIXME: The following is a nicer way than to do this.
        # However, for compatibility, we need to use the same as the
        # tarball server (set up by Lorry) uses.
        # return urllib.quote(url, safe='')

        return quote_url(url)

    def _cache_name(self, url):
        scheme, netloc, path, query, fragment = urlparse.urlsplit(url)
        if scheme != 'file':
            path = os.path.join(self._cachedir, self._escape(url))
        return path

    def has_repo(self, reponame):
        '''Have we already got a cache of a given repo?'''
        url = self._resolver.pull_url(reponame)
        path = self._cache_name(url)
        return self.fs.exists(path)

    def _clone_with_tarball(self, repourl, path):
        tarball_url = urlparse.urljoin(self._tarball_base_url,
                                       self._escape(repourl)) + '.tar'
        try:
            self.fs.makedir(path)
            self._fetch(tarball_url, path)
            self._git(['config', 'remote.origin.url', repourl], cwd=path)
            self._git(['config', 'remote.origin.mirror', 'true'], cwd=path)
            self._git(['config', 'remote.origin.fetch', '+refs/*:refs/*'],
                      cwd=path)
        except BaseException as e:  # pragma: no cover
            if self.fs.exists(path):
                self.fs.removedir(path, force=True)
            return False, 'Unable to extract tarball %s: %s' % (
                tarball_url, e)

        return True, None

    def _cache_repo(self, reponame):
        '''Clone the given repo into the cache.

        If the repo is already cloned, do nothing.

        '''
        errors = []
        if not self.fs.exists(self._cachedir):
            self.fs.makedir(self._cachedir, recursive=True)

        try:
            return self._get_repo(reponame)
        except NotCached as e:
            pass

        repourl = self._resolver.pull_url(reponame)
        path = self._cache_name(repourl)
        if self._tarball_base_url:
            ok, error = self._clone_with_tarball(repourl, path)
            if ok:
                repo = self._get_repo(reponame)
                self._update_repo(repo)
                return repo
            else:
                errors.append(error)
                self._app.status(
                    msg='Using git clone.')

        target = self._mkdtemp(self._cachedir)

        try:
            self._git(['clone', '--mirror', '-n', repourl, target],
                      echo_stderr=self._app.settings['debug'])
        except cliapp.AppException as e:
            errors.append('Unable to clone from %s to %s: %s' %
                          (repourl, target, e))
            if self.fs.exists(target):
                self.fs.removedir(target, recursive=True, force=True)
            raise NoRemote(reponame, errors)

        self.fs.rename(target, path)

        repo = self._get_repo(reponame)
        repo.already_updated = True
        return repo

    def _get_repo(self, reponame):
        '''Return an object representing a cached repository.'''

        if reponame in self._cached_repo_objects:
            return self._cached_repo_objects[reponame]
        else:
            repourl = self._resolver.pull_url(reponame)
            path = self._cache_name(repourl)
            if self.fs.exists(path):
                repo = CachedRepo(path, reponame, repourl)
                self._cached_repo_objects[reponame] = repo
                return repo
        raise NotCached(reponame)

    def _update_repo(self, cachedrepo):  # pragma: no cover
        try:
            cachedrepo.update_remotes(
                echo_stderr=self._app.settings['verbose'])
            cachedrepo.already_updated = True
        except cliapp.AppException:
            raise UpdateError(self)

    def get_updated_repo(self, repo_name,
                         ref=None, refs=None):  # pragma: no cover
        '''Return object representing cached repository.

        If all the specified refs in 'ref' or 'refs' point to SHA1s that are
        already in the repository, or --no-git-update is set, then the
        repository won't be updated.

        '''

        if self._app.settings['no-git-update']:
            self._app.status(msg='Not updating existing git repository '
                                 '%(repo_name)s '
                                 'because of no-git-update being set',
                             chatty=True,
                             repo_name=repo_name)
            return self._get_repo(repo_name)

        if ref is not None and refs is None:
            refs = (ref,)

        if self.has_repo(repo_name):
            repo = self._get_repo(repo_name)
            if refs:
                required_refs = set(refs)
                missing_refs = set()
                for required_ref in required_refs:
                    if morphlib.git.is_valid_sha1(required_ref):
                        try:
                            repo.resolve_ref_to_commit(required_ref)
                            continue
                        except morphlib.gitdir.InvalidRefError:
                            pass
                    missing_refs.add(required_ref)

                if not missing_refs:
                    self._app.status(
                        msg='Not updating git repository %(repo_name)s '
                            'because it already contains %(sha1s)s',
                        chatty=True, repo_name=repo_name,
                        sha1s=_word_join_list(tuple(required_refs)))
                    return repo

            self._app.status(msg='Updating %(repo_name)s',
                             repo_name=repo_name)
            self._update_repo(repo)
            return repo
        else:
            self._app.status(msg='Cloning %(repo_name)s',
                             repo_name=repo_name)
            return self._cache_repo(repo_name)

    def ensure_submodules(self, toplevel_repo,
                          toplevel_ref):  # pragma: no cover
        '''Ensure any submodules of a given repo are cached and up to date.'''

        def submodules_for_repo(repo_path, ref):
            try:
                submodules = morphlib.git.Submodules(self._app, repo_path, ref)
                submodules.load()
                return [(submod.url, submod.commit) for submod in submodules]
            except morphlib.git.NoModulesFileError:
                return []

        done = set()
        subs_to_process = submodules_for_repo(toplevel_repo.dirname,
                                              toplevel_ref)
        while subs_to_process:
            url, ref = subs_to_process.pop()
            done.add((url, ref))

            cached_repo = self.get_updated_repo(url, ref=ref)

            for submod in submodules_for_repo(cached_repo.dirname, ref):
                if submod not in done:
                    subs_to_process.append(submod)
