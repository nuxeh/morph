# -*- coding: utf-8 -*-
# Copyright (C) 2011-2016  Codethink Limited
# Copyright © 2015  Richard Ipsum
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

import contextlib
import errno
import itertools
import os
import pipes
import re
import shutil
import subprocess
import textwrap
import tempfile
import sys

import fs.osfs

import morphlib

'''Utility functions for morph.'''


# It is intentional that if collections does not have OrderedDict that
# simplejson is also used in preference to json, as OrderedDict became
# a member of collections in the same release json got its object_pairs_hook
try: # pragma: no cover
    from collections import OrderedDict
    import json
except ImportError: # pragma: no cover
    from ordereddict import OrderedDict
    import simplejson as json

try:
    from multiprocessing import cpu_count
except NotImplementedError:  # pragma: no cover
    cpu_count = lambda: 1


def indent(string, spaces=4):
    '''Return ``string`` indented by ``spaces`` spaces.

    The final line is not terminated by a newline. This makes it easy
    to use this function for indenting long text for logging: the
    logging library adds a newline, so not including it in the indented
    text avoids a spurious empty line in the log file.

    This also makes the result be a plain ASCII encoded string.

    '''

    if type(string) == unicode:  # pragma: no cover
        string = string.decode('utf-8')
    lines = string.splitlines()
    lines = ['%*s%s' % (spaces, '', line) for line in lines]
    return '\n'.join(lines)


def sanitise_morphology_path(morph_name):
    '''Turn morph_name into a file path to a morphology.

    We support both a file path being provided, and just the morphology
    name for backwards compatibility.

    '''
    # If it has a / it must be a path, so return it unmolested
    if '/' in morph_name:
        return morph_name
    # Must be an old format, which is always name + .morph
    elif not morph_name.endswith('.morph'):
        return morph_name + '.morph'
    # morphology already ends with .morph
    else:
        return morph_name


def make_concurrency(cores=None):
    '''Return the number of concurrent jobs for make.

    This will be given to make as the -j argument.

    '''

    n = cpu_count() if cores is None else cores
    # Research shows that max-jobs should be == cores by default, up to max.
    # 20 cores.
    #
    # http://listmaster.pepperfish.net/pipermail/
    #   baserock-dev-baserock.org/2015-September/013264.html
    return min(n, 20)


def ensure_directory_exists(path):  # pragma: no cover
    # Don't check the folder exists and handle the exception that happens in
    # this case to avoid errors if the folder is created by something else
    # just after the check.
    try:
        os.makedirs(path)
    except OSError as e:
         if e.errno != errno.EEXIST:
             raise


def get_artifact_cache_server(settings): # pragma: no cover
    if settings['artifact-cache-server']:
        return settings['artifact-cache-server']
    if settings['cache-server']:
        return settings['cache-server']
    return None


def get_git_resolve_cache_server(settings): # pragma: no cover
    if settings['git-resolve-cache-server']:
        return settings['git-resolve-cache-server']
    if settings['cache-server']:
        return settings['cache-server']
    return None


def new_artifact_caches(settings):  # pragma: no cover
    '''Create new objects for local and remote artifact caches.

    This includes creating the directories on disk, if missing.

    '''

    artifact_cachedir = os.path.join(settings['cachedir'], 'artifacts')
    ensure_directory_exists(artifact_cachedir)

    lac = morphlib.localartifactcache.LocalArtifactCache(
            fs.osfs.OSFS(artifact_cachedir))

    rac_url = get_artifact_cache_server(settings)
    rac = None
    if rac_url:
        rac = morphlib.remoteartifactcache.RemoteArtifactCache(rac_url)
    return lac, rac


def combine_aliases(app):  # pragma: no cover
    '''Create a full repo-alias set from the app's settings.

    The standard 'baserock:' and 'upstream:' keyed URLs use whatever trove was
    set as 'trove-host'.

    Every trove listed in 'trove-ids' has its own repo-alias created in
    addition to the defaults. We assume these require authenticated access, so
    the keyed URL expansions for these troves are ssh:// URLs for both read and
    write access. This can be overridden by the user if they calculate the full
    repo-alias string and set it in their config manually.

    '''
    trove_host = app.settings['trove-host']
    trove_ids = app.settings['trove-id']
    repo_aliases = app.settings['repo-alias']
    repo_pat = r'^(?P<prefix>[a-z][a-z0-9-]+)=(?P<pull>[^#]+)#(?P<push>[^#]+)$'
    trove_pat = (r'^(?P<prefix>[a-z][a-z0-9-]+)=(?P<path>[^#]+)#'
                 '(?P<pull>[^#]+)#(?P<push>[^#]+)$')
    alias_map = {}
    def _expand(protocol, path):
        if protocol == "git":
            return "git://%s/%s/%%s" % (trove_host, path)
        elif protocol == "ssh":
            return "ssh://git@%s/%s/%%s" % (trove_host, path)
        else:
            raise morphlib.Error(
                'Unknown protocol in trove_id: %s' % protocol)

    if trove_host:
        alias_map['baserock'] = "baserock=%s#%s" % (
            _expand('git', 'baserock'),
            _expand('ssh', 'baserock'))
        alias_map['upstream'] = "upstream=%s#%s" % (
            _expand('git', 'delta'),
            _expand('ssh', 'delta'))
        for trove_id in trove_ids:
            m = re.match(trove_pat, trove_id)
            if m:
                alias_map[m.group('prefix')] = "%s=%s#%s" % (
                    m.group('prefix'),
                    _expand(m.group('pull'), m.group('path')),
                    _expand(m.group('push'), m.group('path')))
            elif '=' not in trove_id and trove_id not in alias_map:
                alias_map[trove_id] = "%s=%s#%s" % (
                    trove_id,
                    _expand('ssh', trove_id),
                    _expand('ssh', trove_id))
    for repo_alias in repo_aliases:
        m = re.match(repo_pat, repo_alias)
        if m:
            alias_map[m.group('prefix')] = repo_alias
        else:
            raise morphlib.Error(
                'Invalid repo-alias: %s' % repo_alias)


    return alias_map.values()


def new_repo_cache(app):  # pragma: no cover
    '''Create a RepoCache instance using settings from app.settings.'''

    gits_dir = os.path.join(app.settings['cachedir'], 'gits')
    tarball_base_url = app.settings['tarball-server']
    git_resolve_cache_url = get_git_resolve_cache_server(app.settings)
    aliases = app.settings['repo-alias']
    repo_alias_resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)

    return morphlib.repocache.RepoCache(
        gits_dir, repo_alias_resolver,
        tarball_base_url=tarball_base_url,
        git_resolve_cache_url=git_resolve_cache_url,
        update_gits=(not app.settings['no-git-update']),
        runcmd_cb=app.runcmd,
        status_cb=app.status,
        verbose=app.settings['verbose'],
        debug=app.settings['debug'])


def env_variable_is_password(key):  # pragma: no cover
    return 'PASSWORD' in key

@contextlib.contextmanager
def hide_password_environment_variables(env):  # pragma: no cover
    is_password = env_variable_is_password
    password_env = { k:v for k,v in env.iteritems() if is_password(k) }
    for k in password_env:
        env[k] = '(value hidden)'
    yield
    for k, v in password_env.iteritems():
        env[k] = v

def log_environment_changes(app, current_env, previous_env): # pragma: no cover
    '''Log the differences between two environments to debug log.'''
    def log_event(key, value, event):
        if env_variable_is_password(key):
            value_msg = '(value hidden)'
        else:
            value_msg = '= "%s"' % value
        app.status(msg='%(event)s environment variable %(key)s %(value)s',
                   event=event, key=key, value=value_msg, chatty=True)

    for key in current_env.keys():
        if key not in previous_env:
            log_event(key, current_env[key], 'new')
        elif current_env[key] != previous_env[key]:
            log_event(key, current_env[key], 'changed')
    for key in previous_env.keys():
        if key not in current_env:
            log_event(key, previous_env[key], 'unset')

# This acquired from rdiff-backup which is GPLv2+ and a patch from 2011
# which has not yet been merged, combined with a tad of tidying from us.
def copyfileobj(inputfp, outputfp, blocksize=1024*1024):  # pragma: no cover
    """Copies file inputfp to outputfp in blocksize intervals"""

    sparse = False
    buf = None
    while 1:
        inbuf = inputfp.read(blocksize)
        if not inbuf: break
        if not buf:
            buf = inbuf
        else:
            buf += inbuf

        # Combine "short" reads
        if (len(buf) < blocksize):
            continue

        buflen = len(buf)
        if buf == "\x00" * buflen:
            outputfp.seek(buflen, os.SEEK_CUR)
            buf = None
            # flag sparse=True, that we seek()ed, but have not written yet
            # The filesize is wrong until we write
            sparse = True
        else:
            outputfp.write(buf)
            buf = None
            # We wrote, so clear sparse.
            sparse = False

    if buf:
        outputfp.write(buf)
    elif sparse:
        outputfp.seek(-1, os.SEEK_CUR)
        outputfp.write("\x00")

def get_bytes_free_in_path(path): # pragma: no cover
    """Returns the bytes free in the filesystem that path is part of"""

    fsinfo = os.statvfs(path)
    return fsinfo.f_bavail * fsinfo.f_bsize

def on_same_filesystem(path_a, path_b): # pragma: no cover
    """Tests whether both paths are on the same fileystem

       Note behaviour may be unexpected on btrfs, since subvolumes
       appear to be on a different device, but share a storage pool.

    """
    # TODO: return true if one path is a subvolume of the other on btrfs?
    return os.stat(path_a).st_dev == os.stat(path_b).st_dev

def unify_space_requirements(tmp_path, tmp_min_size,
                             cache_path, cache_min_size): # pragma: no cover
    """Adjust minimum sizes when paths share a disk.

       Given pairs of path and minimum size, return the minimum sizes such
       that when the paths are on the same disk, the sizes are added together.

    """
    # TODO: make this work for variable number of (path, size) pairs as needed
    #       hint: try list.sort and itertools.groupby
    if not on_same_filesystem(tmp_path, cache_path):
        return tmp_min_size, cache_min_size
    unified_size = tmp_min_size + cache_min_size
    return unified_size, unified_size

def check_disk_available(tmp_path, tmp_min_size,
                         cache_path, cache_min_size): # pragma: no cover
    # if both are on the same filesystem, assume they share a storage pool,
    # so the sum of the two sizes needs to be available
    # TODO: if we need to do this on any more than 2 paths
    #       extend it to take a [(path, min)]
    tmp_min_size, cache_min_size = unify_space_requirements(
        tmp_path, tmp_min_size, cache_path, cache_min_size)
    tmp_size, cache_size = map(get_bytes_free_in_path, (tmp_path, cache_path))
    errors = []
    for path, min in [(tmp_path, tmp_min_size), (cache_path, cache_min_size)]:
        free = get_bytes_free_in_path(path)
        if free < min:
            errors.append('\t%(path)s requires %(min)d bytes free, '
                          'has %(free)d' % locals())
    if not errors:
        return
    raise morphlib.Error('Insufficient space on disk:\n' +
                         '\n'.join(errors) + '\n'
                         'Please run `morph gc`. If the problem persists '
                         'increase the disk size, manually clean up some '
                         'space or reduce the disk space required by the '
                         'tempdir-min-space and cachedir-min-space '
                         'configuration options.')




def find_root(dirname, subdir_name):
    '''Find parent of a directory, at or above a given directory.

    The sought-after directory is indicated by the existence of a
    subdirectory of the indicated name.

    Return path to desired directory, or None if not found.

    '''

    dirname = os.path.normpath(os.path.abspath(dirname))
    while not os.path.isdir(os.path.join(dirname, subdir_name)):
        if dirname == '/':
            return None
        dirname = os.path.dirname(dirname)
    return dirname


def find_leaves(search_dir, subdir_name):
    '''This is like find_root, except it looks towards leaves.

    The directory tree, starting at search_dir is traversed.

    If a directory has a subdirectory called subdir_name, then
    the directory is returned.

    It does not recurse into a leaf's subdirectories.

    '''

    for dirname, subdirs, filenames in os.walk(search_dir):
        if subdir_name in subdirs:
            del subdirs[:]
            yield dirname


def find_leaf(dirname, subdir_name):
    '''This is like find_root, except it looks towards leaves.

    If there are no subdirectories, or more than one, fail.

    '''

    leaves = list(find_leaves(dirname, subdir_name))
    if len(leaves) == 1:
        return leaves[0]
    return None


class EnvironmentAlreadySetError(morphlib.Error):

    def __init__(self, conflicts):
        self.conflicts = conflicts
        morphlib.Error.__init__(
            self, 'Keys %r are already set in the environment' % conflicts)


def parse_environment_pairs(env, pairs):
    '''Add key=value pairs to the environment dict.

    Given a dict and a list of strings of the form key=value,
    set dict[key] = value, unless key is already set in the
    environment, at which point raise an exception.

    This does not modify the passed in dict.

    Returns the extended dict.

    '''

    extra_env = dict(p.split('=', 1) for p in pairs)
    conflicting = [k for k in extra_env if k in env]
    if conflicting:
        raise EnvironmentAlreadySetError(conflicting)

    # Return a dict that is the union of the two
    # This is not the most performant, since it creates
    # 3 unnecessary lists, but I felt this was the most
    # easy to read. Using itertools.chain may be more efficicent
    return dict(env.items() + extra_env.items())


def has_hardware_fp(): # pragma: no cover
    '''
    This function returns whether the binary /proc/self/exe is compiled
    with hardfp _not_ whether the platform is hardfp.

    We expect the binaries on our build platform to be compiled with
    hardfp.

    This is not ideal but at the time of writing this is the only
    reliable way to decide whether our architecture is a hardfp
    architecture.
    '''

    output = subprocess.check_output(['readelf', '-A', '/proc/self/exe'])
    return 'Tag_ABI_VFP_args: VFP registers' in output

def determine_endianness(): # pragma: no cover
    '''
    This function returns whether the host is running
    in big or little endian. This is needed for MIPS.
    '''

    return sys.byteorder

def get_host_architecture(): # pragma: no cover
    '''Get the canonical Morph name for the host's architecture.'''

    machine = os.uname()[-1]

    table = {
        'x86_64': 'x86_64',
        'i386': 'x86_32',
        'i486': 'x86_32',
        'i586': 'x86_32',
        'i686': 'x86_32',
        'armv5l': 'armv5l',
        'armv7l': 'armv7l',
        'armv7b': 'armv7b',
        'armv8l': 'armv8l',
        'armv8b': 'armv8b',
        'aarch64': 'armv8l64',
        'aarch64_be': 'armv8b64',
        'mips': 'mips32',
        'mips64': 'mips64',
        'ppc64': 'ppc64'
    }

    if machine not in table:
        raise morphlib.Error('Unknown host architecture %s' % machine)

    if machine == 'armv7l' and has_hardware_fp():
        return 'armv7lhf'
    elif machine in ('mips', 'mips64'):
        if determine_endianness() == 'big':
            return table[machine]+'b'
        else:
            return table[machine]+'l'

    return table[machine]


def sanitize_environment(env):
    for k in env:
        env[k] = '' if env[k] is None else str(env[k])

def iter_trickle(iterable, limit):
    '''Split an iterable up into `limit` length chunks.'''
    it = iter(iterable)
    while True:
        buf = list(itertools.islice(it, limit))
        if len(buf) == 0:
           break
        yield buf


def get_data_path(relative_path): # pragma: no cover
    '''Return path to a data file in the morphlib Python package.

    ``relative_path`` is the name of the data file, relative to the
    location in morphlib where the data files are.

    '''

    morphlib_dir = os.path.dirname(morphlib.__file__)
    return os.path.join(morphlib_dir, relative_path)


def get_data(relative_path): # pragma: no cover
    '''Return contents of a data file from the morphlib Python package.

    ``relative_path`` is the name of the data file, relative to the
    location in morphlib where the data files are.

    '''

    with open(get_data_path(relative_path)) as f:
        return f.read()


def unshared_cmdline(args, root='/', mounts=()): # pragma: no cover
    '''Describe how to run 'args' inside a separate mount namespace.
    
    This function wraps 'args' in a rather long commandline that ensures
    the subprocess cannot see any of the system's mounts other than those
    listed in 'mounts', and mounts done by that command can only be seen
    by that subprocess and its children. When the subprocess exits all
    of its mounts will be unmounted.
    
    '''
    # We need to do mounts in a different namespace. Unfortunately
    # this means we have to in-line the mount commands in the
    # command-line.
    command = textwrap.dedent(r'''
    mount --make-rprivate /
    root="$1"
    shift
    ''')
    cmdargs = [root]

    # We need to mount all the specified mounts in the namespace,
    # we don't need to unmount them before exiting, as they'll be
    # unmounted when the namespace is no longer used.
    command += textwrap.dedent(r'''
    while true; do
        case "$1" in
        --)
            shift
            break
            ;;
        *)
            mount_point="$1"
            mount_type="$2"
            mount_source="$3"
            shift 3
            path="$root/$mount_point"
            mount -t "$mount_type" "$mount_source" "$path"
            ;;
        esac
    done
    ''')
    for mount_point, mount_type, source in mounts:
        path = os.path.join(root, mount_point)
        if not os.path.exists(path):
            os.makedirs(path)
        cmdargs.extend((mount_point, mount_type, source))
    cmdargs.append('--')

    command += textwrap.dedent(r'''
    exec "$@"
    ''')
    cmdargs.extend(args)

    # The single - is just a shell convention to fill $0 when using -c,
    # since ordinarily $0 contains the program name.
    cmdline = ['unshare', '--mount', '--', 'sh', '-ec', command, '-']
    cmdline.extend(cmdargs)
    return cmdline


def containerised_cmdline(args, cwd='.', root='/', binds=(),
                          mount_proc=False, unshare_net=False,
                          writable_paths=None, **kwargs): # pragma: no cover
    '''
    Describe how to run 'args' inside a linux-user-chroot container.
    
    The subprocess will only be permitted to write to the paths we
    specifically allow it to write to, listed in 'writeable paths'. All
    other locations in the file system will be read-only.
    
    The 'root' parameter allows running the command in a chroot, allowing
    the host file system to be hidden completely except for the paths
    below 'root'.
    
    The 'mount_proc' flag enables mounting of /proc inside 'root'.
    Locations from the file system can be bind-mounted inside 'root' by
    setting 'binds' to a list of (src, dest) pairs. The 'dest'
    directory must be inside 'root'.
    
    The 'mounts' parameter allows mounting of arbitrary file-systems,
    such as tmpfs, before running commands, by setting it to a list of
    (mount_point, mount_type, source) triples.
    
    The subprocess will be run in a separate mount namespace. It can
    optionally be run in a separate network namespace too by setting
    'unshare_net'.
    
    '''

    if not root.endswith('/'):
        root += '/'
    if writable_paths is None:
        writable_paths = (root,)

    cmdargs = ['linux-user-chroot', '--chdir', cwd]
    if unshare_net:
        cmdargs.append('--unshare-net')
    for src, dst in binds:
        # linux-user-chroot's mount target paths are relative to the chroot
        cmdargs.extend(('--mount-bind', src, os.path.relpath(dst, root)))
    print writable_paths
    import pdb; pdb.set_trace()
    for f in os.walk(root):
        print f
    #for d in morphlib.fsutils.invert_paths(os.walk(root), writable_paths):
    #    print d
    for d in morphlib.fsutils.invert_paths(os.walk(root), writable_paths):
        print d
        print root
        print os.path.islink(d)
        print os.path.relpath(d, root)
        if not os.path.islink(d):
            cmdargs.extend(('--mount-readonly', os.path.relpath(d, root)))
            print cmdargs
    if mount_proc:
        proc_target = os.path.join(root, 'proc')
        if not os.path.exists(proc_target):
            os.makedirs(proc_target)
        cmdargs.extend(('--mount-proc', 'proc'))
    cmdargs.append(root)
    cmdargs.extend(args)
    return unshared_cmdline(cmdargs, root=root, **kwargs)


def write_from_dict(filepath, d, validate=lambda x, y: True): #pragma: no cover
    '''Takes a dictionary and appends the contents to a file

    An optional validation callback can be passed to perform validation on
    each value in the dictionary.

    e.g.

        def validation_callback(dictionary_key, dictionary_value):
            if not dictionary_value.isdigit():
                raise Exception('value contains non-digit character(s)')

    Any callback supplied to this function should raise an exception
    if validation fails.
    '''

    # Sort items asciibetically
    # the output of the deployment should not depend
    # on the locale of the machine running the deployment
    items = sorted(d.iteritems(), key=lambda (k, v): [ord(c) for c in v])

    for (k, v) in items:
        validate(k, v)

    with open(filepath, 'a') as f:
        for (_, v) in items:
            f.write('%s\n' % v)

        os.fchown(f.fileno(), 0, 0)
        os.fchmod(f.fileno(), 0644)


def word_join_list(l): # pragma: no cover
    if len(l) == 0:
        return ''
    elif len(l) == 1:
        return l[0]
    else:
        commasep = ', '.join(l[:-1])
        return ' and '.join((commasep, l[-1]))


def fix_chunk_build_mode(system_artifact): # pragma: no cover
    """Give each chunk's in-memory morphology the correct build-mode.

    This function gives each chunk contained in `system_artifact` the
    correct build-mode, rather than having them all be 'staging'.

    Currently, our definitions define build-mode in the entries in the
    chunk list in a given stratum. However, morph expects it to be in
    the chunk morphology when loading, and sets the in-memory
    build-mode to 'staging' by default.

    """
    # This should probably be fixed in morphloader, but I held off on
    # doing that following a discussion on #baserock.
    #
    # https://irclogs.baserock.org/%23baserock.2015-04-21.log.html
    # (at 9:02)
    strata = set(a for a in system_artifact.walk()
                 if a.source.morphology['kind'] == 'stratum')
    chunks = set(a for a in system_artifact.walk()
                 if a.source.morphology['kind'] == 'chunk')
    for chunk, stratum in itertools.product(chunks, strata):
        for spec in stratum.source.morphology['chunks']:
            if chunk.source.morphology['name'] == spec['name']:
                chunk.source.morphology['build-mode'] = \
                    spec['build-mode']


@contextlib.contextmanager
def temp_dir(*args, **kwargs): #pragma: no cover
    cleanup_on_success = kwargs.pop('cleanup_on_success', True)
    td = tempfile.mkdtemp(*args, **kwargs)
    try:
        yield td
    except BaseException as e:
        shutil.rmtree(td, ignore_errors=True)
        raise
    else:
        if cleanup_on_success:
            shutil.rmtree(td, ignore_errors=True)


def copyfileobj(fsrc, fdst, length=16*1024,
                callback=lambda x: None): #pragma: no cover
    ''' This is similar to shutil.copyfileobj
        except this can be passed a callback to monitor copy progress
    '''

    count = 0

    while True:
        buf = fsrc.read(length)
        if buf == '':
            break

        fdst.write(buf)
        count += len(buf)
        callback(count)


class ProgressBar(object):
    ''' A very simple progress bar '''

    TEMPLATE = '%s[%s%s] %.1f/%.1f %s\r'

    def __init__(self, label, expected_size, unit, width=30,
                 progress_char='#', empty_char=' '): #pragma: no cover
        self._label = label
        self._expected_size = expected_size
        self._width = width
        self._unit = unit
        self._block_width = expected_size / float(width);
        self._progress_char = progress_char
        self._empty_char = empty_char

    def show(self, progress): #pragma: no cover
        if sys.stderr.isatty():
            blocks = int(progress / self._block_width);

            s = self.TEMPLATE % (self._label, self._progress_char * blocks,
                                self._empty_char * (self._width - blocks),
                                progress, self._expected_size, self._unit)
            sys.stderr.write(s)
            sys.stderr.flush()


def schemas_directory():  # pragma: no cover
    '''Returns a path to the schemas/ subdirectory of the 'morphlib' module.'''
    code_dir = os.path.dirname(morphlib.__file__)
    return os.path.join(code_dir, 'schemas')
