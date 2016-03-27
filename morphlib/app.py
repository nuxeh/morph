# Copyright (C) 2011-2016  Codethink Limited
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
import errno
import logging
import os
import pipes
import sys
import time
import urlparse
import warnings
import extensions

import morphlib

class InvalidUrlError(cliapp.AppException):

    def __init__(self, parameter, url):
        cliapp.AppException.__init__(
            self, 'Value %s for argument %s is not a url' %
            (url, parameter))

defaults = {
    'trove-host': 'git.baserock.org',
    'trove-id': [],
    'repo-alias': [
        ('freedesktop='
            'git://anongit.freedesktop.org/#'
            'ssh://git.freedesktop.org/'),
        ('gnome='
            'git://git.gnome.org/%s#'
            'ssh://git.gnome.org/git/%s'),
        ('github='
            'git://github.com/%s#'
            'ssh://git@github.com/%s'),
        ('bitbucket='
            'https://bitbucket.org/%s#'
            'ssh://git@bitbucket.org/%s'),
    ],
    'cachedir': os.path.expanduser('~/.cache/morph'),
    'max-jobs': morphlib.util.make_concurrency()
}


class Morph(cliapp.Application):

    def add_settings(self):
        self.settings.boolean(['verbose', 'v'],
                              'write build log on stdout')
        self.settings.boolean(['quiet', 'q'],
                              'show no output unless there is an error')

        self.settings.boolean(['help', 'h'],
                              'show this help message and exit')
        self.settings.boolean(['help-all'],
                              'show help message including hidden subcommands')

        self.settings.string(['build-ref-prefix'],
                             'Prefix to use for temporary build refs',
                             metavar='PREFIX',
                             default=None)
        self.settings.string(['trove-host'],
                             'hostname of Trove instance',
                             metavar='TROVEHOST',
                             default=defaults['trove-host'])
        self.settings.string_list(['trove-id', 'trove-prefix'],
                                  'list of URL prefixes that should be '
                                  'resolved to Trove. The first PREFIX '
                                  'holds special significance, as the '
                                  'primary working prefix.',
                                  metavar='PREFIX, ...',
                                  default=defaults['trove-id'])

        group_advanced = 'Advanced Options'
        self.settings.boolean(['no-git-update'],
                              'do not update the cached git repositories '
                              'automatically',
                              group=group_advanced)
        self.settings.boolean(['build-log-on-stdout'],
                              'internal option for use by distbuild to'
                              'transfer logs from the worker to the'
                              'initiator in real time')
        self.settings.boolean(['debug', 'd'],
                              'show what is happening in much detail',
                              group=group_advanced)
        self.settings.string_list(['repo-alias'],
                                  'list of URL prefix definitions, in the '
                                  'form: example=git://git.example.com/%s'
                                  '#git@git.example.com/%s',
                                  metavar='ALIAS=PREFIX#PULL#PUSH',
                                  default=defaults['repo-alias'],
                                  group=group_advanced)
        self.settings.string(['cache-server'],
                             'HTTP URL of the morph cache server to use. '
                             'If not provided, defaults to '
                             'http://TROVEHOST:8080/',
                             metavar='URL',
                             default=None,
                             group=group_advanced)
        self.settings.string(
            ['artifact-cache-server'],
            'HTTP URL for the artifact cache server; '
            'if not set, then the cache-server setting is used instead',
            metavar='URL',
            default=None,
            group=group_advanced)
        self.settings.string(
            ['git-resolve-cache-server'],
            'HTTP URL for the git ref resolving cache server; '
            'if not set, then the cache-server setting is used instead',
            metavar='URL',
            default=None,
            group=group_advanced)
        self.settings.string(['tarball-server'],
                             'base URL to download tarballs. '
                             'If not provided, defaults to '
                             'http://TROVEHOST/tarballs/',
                             metavar='URL',
                             default=None,
                             group=group_advanced)

        group_build = 'Build Options'
        self.settings.integer(['max-jobs'],
                              'run at most N parallel jobs with make (default '
                              'is to a value based on the number of CPUs '
                              'in the machine running morph',
                              metavar='N',
                              default=defaults['max-jobs'],
                              group=group_build)
        self.settings.boolean(['no-ccache'], 'do not use ccache',
                              group=group_build)
        self.settings.boolean(['no-distcc'],
                              'do not use distcc (default: true)',
                              group=group_build, default=True)
        self.settings.boolean(['push-build-branches'],
                              'always push temporary build branches to the '
                              'remote repository',
                              group=group_build)
        self.settings.boolean(['partial'],
                              'only build up to a given chunk',
                              default=False,
                              group=group_build)
        self.settings.choice (['local-changes'],
                              ['include', 'ignore'],
                              'the `build` and `deploy` commands detect '
                              'uncommitted/unpushed local changes and operate '
                              'operate from a temporary branch containing '
                              'those changes. Disable this behaviour with the '
                              '`ignore` setting.',
                              group=group_build)

        group_storage = 'Storage Options'
        self.settings.string(['tempdir'],
                             'temporary directory to use for builds '
                             '(this is separate from just setting $TMPDIR '
                             'or /tmp because those are used internally '
                             'by things that cannot be on NFS, but '
                             'this setting can point at a directory in '
                             'NFS)',
                             metavar='DIR',
                             default=None,
                             group=group_storage)
        self.settings.string(['cachedir'],
                             'cache git repositories and build results in DIR',
                             metavar='DIR',
                             group=group_storage,
                             default=defaults['cachedir'])
        self.settings.string(['compiler-cache-dir'],
                             'cache compiled objects in DIR/REPO. If not '
                             'provided, defaults to CACHEDIR/ccache/',
                             metavar='DIR',
                             group=group_storage,
                             default=None)
        # The tempdir default size of 4G comes from the staging area needing to
        # be the size of the largest known system, plus the largest repository,
        # plus the largest working directory.
        # The largest system is 2G, linux is the largest git repository at
        # 700M, the checkout of this is 600M. This is rounded up to 4G because
        # there are likely to be file-system overheads.
        self.settings.bytesize(['tempdir-min-space'],
                               'Immediately fail to build if the directory '
                               'specified by tempdir has less space remaining '
                               'than SIZE bytes (default: %default)',
                               metavar='SIZE',
                               group=group_storage,
                               default='4G')
        # The cachedir default size of 4G comes from twice the size of the
        # largest system artifact.
        # It's twice the size because it needs space for all the chunks that
        # make up the system artifact as well.
        # The git cache and ccache are also kept in cachedir, but it's hard to
        # estimate size needed for the git cache, and it tends to not grow
        # too quickly once everything is checked out.
        # ccache is self-managing so does not need much extra attention
        self.settings.bytesize(['cachedir-min-space'],
                               'Immediately fail to build if the directory '
                               'specified by cachedir has less space '
                               'remaining than SIZE bytes (default: %default)',
                               metavar='SIZE',
                               group=group_storage,
                               default='4G')

    def check_time(self):
        # Check that the current time is not far in the past.
        if time.localtime(time.time()).tm_year < 2012:
            raise morphlib.Error(
                'System time is far in the past, please set your system clock')

    def setup(self):
        self.status_prefix = ''

        self.add_subcommand('help-extensions', self.help_extensions)

    def log_config(self):
        with morphlib.util.hide_password_environment_variables(os.environ):
            cliapp.Application.log_config(self)

        def pretty_warnings(message, category, filename, lineno,
                            file=None, line=None):
            return 'WARNING: %s\n' % (message)

        warnings.formatwarning = pretty_warnings

    def process_args(self, args):
        self.check_time()

        if self.settings['help']:
            self.help(args)
            sys.exit(0)

        if self.settings['help-all']:
            self.help_all(args)
            sys.exit(0)

        if self.settings['build-ref-prefix'] is None:
            if self.settings['trove-id']:
                self.settings['build-ref-prefix'] = os.path.join(
                        self.settings['trove-id'][0], 'builds')
            else:
                self.settings['build-ref-prefix'] = "baserock/builds"

        # Combine the aliases into repo-alias before passing on to normal
        # command processing.  This means everything from here on down can
        # treat settings['repo-alias'] as the sole source of prefixes for git
        # URL expansion.
        self.settings['repo-alias'] = morphlib.util.combine_aliases(self)
        if self.settings['cache-server'] is None:
            self.settings['cache-server'] = 'http://%s:8080/' % (
                self.settings['trove-host'])
        if self.settings['tarball-server'] is None:
            self.settings['tarball-server'] = 'http://%s/tarballs/' % (
                self.settings['trove-host'])
        if self.settings['compiler-cache-dir'] is None:
            self.settings['compiler-cache-dir'] = os.path.join(
                    self.settings['cachedir'], 'ccache')
        if self.settings['tempdir'] is None:
            tmpdir_base = os.environ.get('TMPDIR', '/tmp')
            tmpdir = os.path.join(tmpdir_base, 'morph_tmp')
            self.settings['tempdir'] = tmpdir

        if self.settings['tarball-server']:
            url_split = urlparse.urlparse(self.settings['tarball-server'])
            if not (url_split.netloc and
                    url_split.scheme in ('http', 'https', 'file')):
                raise InvalidUrlError('tarball-server',
                                      self.settings['tarball-server'])

        if 'MORPH_DUMP_PROCESSED_CONFIG' in os.environ:
            self.settings.dump_config(sys.stdout)
            sys.exit(0)

        tmpdir = self.settings['tempdir']
        for required_dir in (os.path.join(tmpdir, 'chunks'),
                             os.path.join(tmpdir, 'staging'),
                             os.path.join(tmpdir, 'deployments'),
                             self.settings['cachedir']):
            # Don't check the folder exists and handle the exception that
            # happens in this case to avoid errors if the folder is created
            # by something else just after the check.
            try:
                os.makedirs(required_dir)
            except OSError as e:
                if e.errno != errno.EEXIST:
                     raise

        cliapp.Application.process_args(self, args)

    def setup_plugin_manager(self):
        cliapp.Application.setup_plugin_manager(self)

        s = os.path.join(os.path.dirname(morphlib.__file__), 'plugins')
        if not s in self.pluginmgr.locations:
            self.pluginmgr.locations.append(s)

        s = os.environ.get('MORPH_PLUGIN_PATH', '').split(':')
        for path in s:
            self.pluginmgr.locations.append(path)

        self.hookmgr = cliapp.HookManager()
        self.hookmgr.new('new-build-command', cliapp.FilterHook())

    def itertriplets(self, args):
        '''Generate repo, ref, filename triples from args.'''

        if (len(args) % 3) != 0:
            raise cliapp.AppException('Argument list must have full triplets')

        while args:
            assert len(args) >= 2, args
            yield (args[0], args[1],
                   morphlib.util.sanitise_morphology_path(args[2]))
            args = args[3:]

    def _write_status(self, text):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
        self.output.write('%s %s\n' % (timestamp, text))
        self.output.flush()

    def status(self, **kwargs):
        '''Show user a status update.

        The keyword arguments are formatted and presented to the user in
        a pleasing manner. Some keywords are special:

        * ``msg`` is the message text; it can use ``%(foo)s`` to embed the
          value of keyword argument ``foo``
        * ``chatty`` should be true when the message is only informative,
          and only useful for users who want to know everything (--debug)
        * ``error`` should be true when it is an error message

        All other keywords are ignored unless embedded in ``msg``.

        The ``self.status_prefix`` string is prepended to the output.
        It is set to the empty string by default.

        '''

        assert 'msg' in kwargs
        text = self.status_prefix + (kwargs['msg'] % kwargs)

        error = kwargs.get('error', False)
        chatty = kwargs.get('chatty', False)
        quiet = self.settings['quiet']
        debug = self.settings['debug']

        if error:
            logging.error(text)
        elif chatty:
            logging.debug(text)
        else:
            logging.info(text)

        ok = debug or error or (not quiet and not chatty)
        if ok:
            self._write_status(text)

    def _commandline_as_message(self, argv, args):
        '''Create a status string for a command that's about to be executed.'''

        commands = []
        for command in [argv] + list(args):
            if isinstance(command, list):
                command_str = ' '.join(map(pipes.quote, command))
            else:
                command_str = pipes.quote(command)
            commands.append(command_str)

        return '# ' + ' | '.join(commands)

    def _prepare_for_runcmd(self, argv, args, kwargs):
        if 'env' not in kwargs:
            kwargs['env'] = dict(os.environ)

        if 'print_command' in kwargs:
            print_command = kwargs['print_command']
            del kwargs['print_command']
        else:
            print_command = True

        if print_command and self.settings['debug']:
            # Don't call self.status() here, to avoid writing the message to
            # the log as well as to the console. The cliapp.runcmd() function
            # will also log the command, and it's messy having it logged twice.
            self._write_status(self._commandline_as_message(argv, args))

        # Log the environment.
        prev = getattr(self, 'prev_env', os.environ)
        morphlib.util.log_environment_changes(self, kwargs['env'], prev)
        self.prev_env = kwargs['env']

    def runcmd(self, argv, *args, **kwargs):
        self._prepare_for_runcmd(argv, args, kwargs)
        return cliapp.Application.runcmd(self, argv, *args, **kwargs)

    def runcmd_unchecked(self, argv, *args, **kwargs):
        self.status(msg='prep run_unch')
        self._prepare_for_runcmd(argv, args, kwargs)
        self.status(msg='run_unch')
        return cliapp.Application.runcmd_unchecked(self, argv, *args, **kwargs)

    def parse_args(self, args, configs_only=False):
        return self.settings.parse_args(args,
                         configs_only=configs_only,
                         arg_synopsis=self.arg_synopsis,
                         cmd_synopsis=self.cmd_synopsis,
                         compute_setting_values=self.compute_setting_values,
                         add_help_option=False)

    def _help(self, show_all):
        pp = self.settings.build_parser(
            configs_only=True,
            arg_synopsis=self.arg_synopsis,
            cmd_synopsis=self.cmd_synopsis,
            all_options=show_all,
            add_help_option=False)
        text = pp.format_help()
        self.output.write(text)

    def _help_topic(self, topic):
        if topic in self.subcommands:
            usage = self._format_usage_for(topic)
            description = self._format_subcommand_help(topic)
            text = '%s\n\n%s' % (usage, description)
            self.output.write(text)
        elif topic in extensions.list_extensions():
            definitions_repo = morphlib.definitions_repo.open(
                    '.', False, self)
            name, kind = os.path.splitext(topic)
            try:
                with extensions.get_extension_filename(
                        definitions_repo,
                        name,
                        kind + '.help', executable=False) as fname:
                    with open(fname, 'r') as f:
                        help_data = morphlib.yamlparse.load(f.read())
                        print help_data['help']
            except extensions.ExtensionError:
                    raise cliapp.AppException(
                            'Help not available for extension %s' % topic)
        else:
            raise cliapp.AppException(
                    'Unknown subcommand or extension %s' % topic)

    def help(self, args): # pragma: no cover
        '''Print help.'''
        if args:
            self._help_topic(args[0])
        else:
            self._help(False)

    def help_all(self, args): # pragma: no cover
        '''Print help, including hidden subcommands.'''
        self._help(True)

    def help_extensions(self, args):
        exts = extensions.list_extensions()
        template = "Extensions:\n    %s\n"
        ext_string = '\n    '.join(exts)
        self.output.write(template % (ext_string))
