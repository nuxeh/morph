# Copyright (C) 2012-2016 Codethink Limited
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
import morphlib


class ArtifactInspectionPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('generate-manifest-genivi',
                                self.generate_manifest)

    def disable(self):
        pass

    def generate_manifest(self, args):
        raise cliapp.AppException('This plugin has been moved to '
            'definitions.git, as: scripts/system-manifest.py\n'
            'Please run that script directly instead.')
