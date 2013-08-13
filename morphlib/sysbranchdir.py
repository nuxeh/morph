# Copyright (C) 2013  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import cliapp
import os
import urlparse
import uuid

import morphlib


class SystemBranchDirectoryAlreadyExists(morphlib.Error):

    def __init__(self, root_directory):
        self.msg = (
            "%s: File exists" % 
            root_directory)


class NotInSystemBranch(morphlib.Error):

    def __init__(self, dirname):
        self.msg = (
            "Can't find the system branch directory.\n"
            "Morph must be built and deployed within "
            "the system branch checkout.")


class SystemBranchDirectory(object):

    '''A directory containing a checked out system branch.'''

    def __init__(self,
        root_directory, root_repository_url, system_branch_name):
        self.root_directory = root_directory
        self.root_repository_url = root_repository_url
        self.system_branch_name = system_branch_name

    @property
    def _magic_path(self):
        return os.path.join(self.root_directory, '.morph-system-branch')

    @property
    def _config_path(self):
        return os.path.join(self._magic_path, 'config')

    def set_config(self, key, value):
        '''Set a configuration key/value pair.'''
        cliapp.runcmd(['git', 'config', '-f', self._config_path, key, value])

    def get_config(self, key):
        '''Get a configuration value for a given key.'''
        value = cliapp.runcmd(['git', 'config', '-f', self._config_path, key])
        return value.strip()

    def get_git_directory_name(self, repo_url):
        '''Return directory pathname for a given git repository.

        If the URL is a real one (not aliased), the schema and leading //
        are removed from it, as is a .git suffix.

        '''

        # Parse the URL. If the path component is absolute, we assume
        # it's a real URL; otherwise, an aliased URL.
        parts = urlparse.urlparse(repo_url)

        if os.path.isabs(parts.path):
            # Remove .git suffix, if any.
            path = parts.path
            if path.endswith('.git'):
                path = path[:-len('.git')]

            # Add the domain name etc (netloc). Ignore any other parts.
            # Note that we _know_ the path starts with a slash, so we avoid
            # adding one here.
            relative = '%s%s' % (parts.netloc, path)
        else:
            relative = repo_url

        # Remove anyleading slashes, or os.path.join below will only
        # use the relative part (since it's absolute, not relative).
        while relative.startswith('/'):
            relative = relative[1:]

        return os.path.join(self.root_directory, relative)

    def clone_cached_repo(self, cached_repo, git_branch_name, checkout_ref):
        '''Clone a cached git repository into the system branch directory.

        The cloned repository will NOT have the system branch's git branch
        checked out: instead, checkout_ref is checked out (this is for
        backwards compatibility with older implementation of "morph
        branch"; it may change later). The system branch's git branch
        is NOT created: the caller will need to do that. Submodules are
        NOT checked out.

        The "origin" remote will be set to follow the cached repository's
        upstream. Remotes are not updated.

        '''

        # Do the clone.
        dirname = self.get_git_directory_name(cached_repo.original_name)
        gd = morphlib.gitdir.clone_from_cached_repo(
            cached_repo, dirname, checkout_ref)

        # Remember the repo name we cloned from in order to be able
        # to identify the repo again later using the same name, even
        # if the user happens to rename the directory.
        gd.set_config('morph.repository', cached_repo.original_name)

        # Create a UUID for the clone. We will use this for naming
        # temporary refs, e.g. for building.
        gd.set_config('morph.uuid', uuid.uuid4().hex)

        # Configure the "origin" remote to use the upstream git repository,
        # and not the locally cached copy.
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            cached_repo.app.settings['repo-alias'])
        gd.set_remote_fetch_url('origin', resolver.pull_url(cached_repo.url))
        gd.set_config(
            'url.%s.pushInsteadOf' %
                resolver.push_url(cached_repo.original_name),
            resolver.pull_url(cached_repo.url))

        return gd

    def list_git_directories(self):
        '''List all git directories in a system branch directory.

        The list will contain zero or more GitDirectory objects.

        '''

        gitdirs = []
        for dirname, subdirs, filenames in os.walk(self.root_directory):
            if os.path.isdir(os.path.join(dirname, '.git')):
                del subdirs[:]
                gitdirs.append(morphlib.gitdir.GitDirectory(dirname))

        return gitdirs


def create(root_directory, root_repository_url, system_branch_name):
    '''Create a new system branch directory on disk.

    Return a SystemBranchDirectory object that represents the directory.

    The directory MUST NOT exist already. If it does,
    SystemBranchDirectoryAlreadyExists is raised.

    Note that this does NOT check out the root repository, or do any
    other git cloning.

    '''

    if os.path.exists(root_directory):
        raise SystemBranchDirectoryAlreadyExists(root_directory)

    magic_dir = os.path.join(root_directory, '.morph-system-branch')
    os.makedirs(root_directory)
    os.mkdir(magic_dir)

    sb = SystemBranchDirectory(
        root_directory, root_repository_url, system_branch_name)
    sb.set_config('branch.name', system_branch_name)
    sb.set_config('branch.root', root_repository_url)
    sb.set_config('branch.uuid', uuid.uuid4().hex)

    return sb


def open(root_directory):
    '''Open an existing system branch directory.'''

    # Ugly hack follows.
    sb = SystemBranchDirectory(root_directory, None, None)
    root_repository_url = sb.get_config('branch.root')
    system_branch_name = sb.get_config('branch.name')

    return SystemBranchDirectory(
        root_directory, root_repository_url, system_branch_name)


def open_from_within(dirname):
    '''Open a system branch directory, given any directory.

    The directory can be within the system branch root directory,
    or it can be a parent, in some cases. If each parent on the
    path from dirname to the system branch root directory has no
    siblings, this function will find it.

    '''

    root_directory = morphlib.util.find_root(
        dirname, '.morph-system-branch')
    if root_directory is None:
        root_directory = morphlib.util.find_leaf(
            dirname, '.morph-system-branch')
    if root_directory is None:
        raise NotInSystemBranch(dirname)
    return morphlib.sysbranchdir.open(root_directory)
