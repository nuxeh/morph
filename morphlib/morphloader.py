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
#
# =*= License: GPL-2 =*=


import collections
import warnings
import yaml

import morphlib


class MorphologySyntaxError(morphlib.Error):
    pass


class MorphologyNotYamlError(MorphologySyntaxError):

    def __init__(self, morphology, errmsg):
        self.msg = 'Syntax error in morphology %s:\n%s' % (morphology, errmsg)


class NotADictionaryError(MorphologySyntaxError):

    def __init__(self, morph_filename):
        self.msg = 'Not a dictionary: morphology %s' % morph_filename


class MorphologyValidationError(morphlib.Error):
    pass


class UnknownKindError(MorphologyValidationError):

    def __init__(self, kind, morph_filename):
        self.msg = (
            'Unknown kind %s in morphology %s' % (kind, morph_filename))


class MissingFieldError(MorphologyValidationError):

    def __init__(self, field, morphology_name):
        self.field = field
        self.morphology_name = morphology_name
        self.msg = (
            'Missing field %s from morphology %s' % (field, morphology_name))


class InvalidFieldError(MorphologyValidationError):

    def __init__(self, field, morphology_name):
        self.field = field
        self.morphology_name = morphology_name
        self.msg = (
            'Field %s not allowed in morphology %s' % (field, morphology_name))


class InvalidTypeError(MorphologyValidationError):

    def __init__(self, field, expected, actual, morphology_name):
        self.field = field
        self.expected = expected
        self.actual = actual
        self.morphology_name = morphology_name
        self.msg = (
            'Field %s expected type %s, got %s in morphology %s' %
            (field, expected, actual, morphology_name))


class UnknownArchitectureError(MorphologyValidationError):

    def __init__(self, arch, morph_filename):
        self.msg = ('Unknown architecture %s in morphology %s'
                    % (arch, morph_filename))


class UnknownBuildSystemError(MorphologyValidationError):

    def __init__(self, build_system, morph_filename):
        self.msg = ('Undefined build system %s in morphology %s'
                    % (build_system, morph_filename))


class NoStratumBuildDependenciesError(MorphologyValidationError):

    def __init__(self, stratum_name, morph_filename):
        self.msg = (
            'Stratum %s has no build dependencies in %s' %
                (stratum_name, morph_filename))


class EmptyStratumError(MorphologyValidationError):

    def __init__(self, stratum_name, morph_filename):
        self.msg = (
            'Stratum %s has no chunks in %s' %
                (stratum_name, morph_filename))


class DuplicateChunkError(MorphologyValidationError):

    def __init__(self, stratum_name, chunk_name):
        self.stratum_name = stratum_name
        self.chunk_name = chunk_name
        MorphologyValidationError.__init__(
            self, 'Duplicate chunk %(chunk_name)s '\
                  'in stratum %(stratum_name)s' % locals())


class EmptyRefError(MorphologyValidationError):

    def __init__(self, ref_location, morph_filename):
        self.ref_location = ref_location
        self.morph_filename = morph_filename
        MorphologyValidationError.__init__(
            self, 'Empty ref found for %(ref_location)s '\
                  'in %(morph_filename)s' % locals())


class ChunkSpecRefNotStringError(MorphologyValidationError):

    def __init__(self, ref_value, chunk_name, stratum_name):
        self.ref_value = ref_value
        self.chunk_name = chunk_name
        self.stratum_name = stratum_name
        MorphologyValidationError.__init__(
            self, 'Ref %(ref_value)s for %(chunk_name)s '\
                  'in stratum %(stratum_name)s is not a string' % locals())


class ChunkSpecConflictingFieldsError(MorphologyValidationError):

    def __init__(self, fields, chunk_name, stratum_name):
        self.chunk_name = chunk_name
        self.stratum_name = stratum_name
        self.fields = fields
        MorphologyValidationError.__init__(
            self, 'Conflicting fields "%s" for %s in stratum %s.' % (
                ', and '.join(fields), chunk_name, stratum_name))


class ChunkSpecNoBuildInstructionsError(MorphologyValidationError):

    def __init__(self, chunk_name, stratum_name):
        self.chunk_name = chunk_name
        self.stratum_name = stratum_name
        self.msg = (
            'Chunk %(chunk_name)s in stratum %(stratum_name)s has no '
            'build-system defined, and no chunk .morph file referenced '
            'either. Please specify how to build the chunk, either by setting '
            '"build-system: " in the stratum, or adding a chunk .morph file '
            'and setting "morph: " in the stratum.' % locals())


class SystemStrataNotListError(MorphologyValidationError):

    def __init__(self, system_name, strata_type):
        self.system_name = system_name
        self.strata_type = strata_type
        typename = strata_type.__name__
        MorphologyValidationError.__init__(
            self, 'System %(system_name)s has the wrong type for its strata: '\
                  '%(typename)s, expected list' % locals())


class DuplicateStratumError(MorphologyValidationError):

    def __init__(self, system_name, stratum_name):
        self.system_name = system_name
        self.stratum_name = stratum_name
        MorphologyValidationError.__init__(
            self, 'Duplicate stratum %(stratum_name)s '\
                  'in system %(system_name)s' % locals())


class SystemStratumSpecsNotMappingError(MorphologyValidationError):

    def __init__(self, system_name, strata):
        self.system_name = system_name
        self.strata = strata
        MorphologyValidationError.__init__(
            self, 'System %(system_name)s has stratum specs '\
                  'that are not mappings.' % locals())


class EmptySystemError(MorphologyValidationError):

    def __init__(self, system_name):
        MorphologyValidationError.__init__(
            self, 'System %(system_name)s has no strata.' % locals())


class DependsOnSelfError(MorphologyValidationError):

    def __init__(self, name, filename):
        msg = ("Stratum %(name)s build-depends on itself (%(filename)s)"
               % locals())
        MorphologyValidationError.__init__(self, msg)


class MultipleValidationErrors(MorphologyValidationError):

    def __init__(self, name, errors):
        self.name = name
        self.errors = errors
        self.msg = 'Multiple errors when validating %(name)s:'
        for error in errors:
            self.msg += ('\n' + str(error))


class DuplicateDeploymentNameError(MorphologyValidationError):

    def __init__(self, cluster_filename, duplicates):
        self.duplicates = duplicates
        self.cluster_filename = cluster_filename
        morphlib.Error.__init__(self,
            'Cluster %s contains the following duplicate deployment names:%s'
            % (cluster_filename, '\n    ' + '\n    '.join(duplicates)))


class MorphologyDumper(yaml.SafeDumper):
    keyorder = (
        'name',
        'kind',
        'description',
        'arch',
        'strata',
        'configuration-extensions',
        'morph',
        'repo',
        'ref',
        'unpetrify-ref',
        'build-depends',
        'build-mode',
        'artifacts',
        'max-jobs',
        'products',
        'chunks',
        'build-system',
        'pre-configure-commands',
        'configure-commands',
        'post-configure-commands',
        'pre-build-commands',
        'build-commands',
        'pre-test-commands',
        'test-commands',
        'post-test-commands',
        'post-build-commands',
        'pre-install-commands',
        'install-commands',
        'post-install-commands',
        'artifact',
        'include',
        'systems',
        'deploy-defaults',
        'deploy',
        'type',
        'location',
    )

    @classmethod
    def _iter_in_global_order(cls, mapping):
        for key in cls.keyorder:
            if key in mapping:
                yield key, mapping[key]
        for key in sorted(mapping.iterkeys()):
            if key not in cls.keyorder:
                yield key, mapping[key]

    @classmethod
    def _represent_dict(cls, dumper, mapping):
        return dumper.represent_mapping('tag:yaml.org,2002:map',
                                        cls._iter_in_global_order(mapping))

    @classmethod
    def _represent_str(cls, dumper, orig_data):
        fallback_representer = yaml.representer.SafeRepresenter.represent_str
        try:
            data = unicode(orig_data, 'ascii')
            if data.count('\n') == 0:
                return fallback_representer(dumper, orig_data)
        except UnicodeDecodeError:
            try:
                data = unicode(orig_data, 'utf-8')
                if data.count('\n') == 0:
                    return fallback_representer(dumper, orig_data)
            except UnicodeDecodeError:
                return fallback_representer(dumper, orig_data)
        return dumper.represent_scalar(u'tag:yaml.org,2002:str',
                                       data, style='|')

    @classmethod
    def _represent_unicode(cls, dumper, data):
        if data.count('\n') == 0:
            return yaml.representer.SafeRepresenter.represent_unicode(dumper,
                                                                      data)
        return dumper.represent_scalar(u'tag:yaml.org,2002:str',
                                       data, style='|')

    def __init__(self, *args, **kwargs):
        yaml.SafeDumper.__init__(self, *args, **kwargs)
        self.add_representer(dict, self._represent_dict)
        self.add_representer(str, self._represent_str)
        self.add_representer(unicode, self._represent_unicode)


class MorphologyLoader(object):

    '''Load morphologies from disk, or save them back to disk.'''

    _required_fields = {
        'chunk': [
            'name',
        ],
        'stratum': [
            'name',
        ],
        'system': [
            'name',
            'arch',
            'strata',
        ],
        'cluster': [
          'name',
          'systems',
        ],
    }

    _static_defaults = {
        'chunk': {
            'description': '',
            'pre-configure-commands': None,
            'configure-commands': None,
            'post-configure-commands': None,
            'pre-build-commands': None,
            'build-commands': None,
            'post-build-commands': None,
            'pre-test-commands': None,
            'test-commands': None,
            'post-test-commands': None,
            'pre-install-commands': None,
            'install-commands': None,
            'post-install-commands': None,
            'pre-strip-commands': None,
            'strip-commands': None,
            'post-strip-commands': None,
            'devices': [],
            'products': [],
            'max-jobs': None,
            'build-system': 'manual',
            'build-mode': 'staging',
            'prefix': '/usr',
            'system-integration': [],
        },
        'stratum': {
            'chunks': [],
            'description': '',
            'build-depends': [],
            'products': [],
        },
        'system': {
            'description': '',
            'arch': None,
            'configuration-extensions': [],
        },
        'cluster': {
            'description': '',
        },
    }

    def __init__(self,
                 predefined_build_systems={}):
        self._predefined_build_systems = predefined_build_systems.copy()

        if 'manual' not in self._predefined_build_systems:
            self._predefined_build_systems['manual'] = \
                morphlib.buildsystem.ManualBuildSystem()

    def parse_morphology_text(self, text, morph_filename):
        '''Parse a textual morphology.

        The text may be a string, or an open file handle.

        Return the new Morphology object, or raise an error indicating
        the problem. This method does minimal validation: a syntactically
        correct morphology is fine, even if none of the fields are
        valid. It also does not set any default values for any of the
        fields. See validate and set_defaults.

        '''

        try:
            obj = yaml.safe_load(text)
        except yaml.error.YAMLError as e:
            raise MorphologyNotYamlError(morph_filename, e)

        if not isinstance(obj, dict):
            raise NotADictionaryError(morph_filename)

        m = morphlib.morphology.Morphology(obj)
        m.filename = morph_filename
        return m

    def load_from_string(self, string,
                         filename='string'):  # pragma: no cover
        '''Load a morphology from a string.

        Return the Morphology object.

        '''

        if string is None:
            return None

        m = self.parse_morphology_text(string, filename)
        self.validate(m)
        self.set_commands(m)
        self.set_defaults(m)
        return m

    def load_from_file(self, filename):
        '''Load a morphology from a named file.

        Return the Morphology object.

        '''

        with open(filename) as f:
            text = f.read()
        return self.load_from_string(text, filename=filename)

    def save_to_string(self, morphology):
        '''Return normalised textual form of morphology.'''

        return yaml.dump(morphology.data, Dumper=MorphologyDumper,
                         default_flow_style=False)

    def save_to_file(self, filename, morphology):
        '''Save a morphology object to a named file.'''

        text = self.save_to_string(morphology)
        with morphlib.savefile.SaveFile(filename, 'w') as f:
            f.write(text)

    def validate(self, morph):
        '''Validate a morphology.'''

        # Validate that the kind field is there.
        self._require_field('kind', morph)

        # The rest of the validation is dependent on the kind.
        kind = morph['kind']
        if kind not in ('system', 'stratum', 'chunk', 'cluster'):
            raise UnknownKindError(morph['kind'], morph.filename)

        required = ['kind'] + self._required_fields[kind]
        allowed = self._static_defaults[kind].keys()
        self._require_fields(required, morph)
        self._deny_unknown_fields(required + allowed, morph)

        getattr(self, '_validate_%s' % kind)(morph)

    def _validate_cluster(self, morph):
        # Deployment names must be unique within a cluster
        deployments = collections.Counter()
        for system in morph['systems']:
            deployments.update(system['deploy'].iterkeys())
            if 'subsystems' in system:
                deployments.update(self._get_subsystem_names(system))
        duplicates = set(deployment for deployment, count
                         in deployments.iteritems() if count > 1)
        if duplicates:
            raise DuplicateDeploymentNameError(morph.filename, duplicates)

    def _get_subsystem_names(self, system): # pragma: no cover
        for subsystem in system.get('subsystems', []):
            for name in subsystem['deploy'].iterkeys():
                yield name
            for name in self._get_subsystem_names(subsystem):
                yield name

    def _validate_system(self, morph):
        # A system must contain at least one stratum
        strata = morph['strata']
        if (not isinstance(strata, collections.Iterable)
            or isinstance(strata, collections.Mapping)):

            raise SystemStrataNotListError(morph['name'],
                                           type(strata))

        if not strata:
            raise EmptySystemError(morph['name'])

        if not all(isinstance(o, collections.Mapping) for o in strata):
            raise SystemStratumSpecsNotMappingError(morph['name'], strata)

        # All stratum names should be unique within a system.
        names = set()
        for spec in strata:
            name = spec['morph']
            if name in names:
                raise DuplicateStratumError(morph['name'], name)
            names.add(name)

        # Architecture name must be known.
        if morph['arch'] not in morphlib.valid_archs:
            raise UnknownArchitectureError(morph['arch'], morph.filename)

    def _validate_stratum(self, morph):
        # Require at least one chunk.
        if len(morph.get('chunks', [])) == 0:
            raise EmptyStratumError(morph['name'], morph.filename)

        # Require build-dependencies for the stratum itself, unless
        # it has chunks built in bootstrap mode.
        if 'build-depends' in morph:
            if not isinstance(morph['build-depends'], list):
                raise InvalidTypeError(
                    'build-depends', list, type(morph['build-depends']),
                    morph['name'])
            for dep in morph['build-depends']:
                if dep['morph'] == morph.filename:
                    raise DependsOnSelfError(morph['name'], morph.filename)
        else:
            for spec in morph['chunks']:
                if spec.get('build-mode') in ['bootstrap', 'test']:
                    break
            else:
                raise NoStratumBuildDependenciesError(
                    morph['name'], morph.filename)

        # All chunk names must be unique within a stratum.
        names = set()
        for spec in morph['chunks']:
            name = spec['name']
            if name in names:
                raise DuplicateChunkError(morph['name'], name)
            names.add(name)

        # Check each reference to a chunk.
        for spec in morph['chunks']:
            chunk_name = spec['name']

            # All chunk refs must be strings.
            if 'ref' in spec:
                ref = spec['ref']
                if ref == None:
                    raise EmptyRefError(spec['name'], morph.filename)
                elif not isinstance(ref, basestring):
                    raise ChunkSpecRefNotStringError(
                        ref, spec['name'], morph.filename)

            # The build-depends field must be a list.
            if 'build-depends' in spec:
                if not isinstance(spec['build-depends'], list):
                    raise InvalidTypeError(
                        '%s.build-depends' % chunk_name, list,
                        type(spec['build-depends']), morph['name'])

            # Either 'morph' or 'build-system' must be specified.
            if 'morph' in spec and 'build-system' in spec:
                raise ChunkSpecConflictingFieldsError(
                    ['morph', 'build-system'], chunk_name, morph.filename)
            if 'morph' not in spec and 'build-system' not in spec:
                raise ChunkSpecNoBuildInstructionsError(
                    chunk_name, morph.filename)

    @classmethod
    def _validate_chunk(cls, morphology):
        errors = []

        if 'products' in morphology:
            cls._validate_products(morphology['name'],
                                   morphology['products'], errors)

        for key in MorphologyDumper.keyorder:
            if key.endswith('-commands') and key in morphology:
                cls._validate_commands(morphology['name'], key,
                                       morphology[key], errors)

        if len(errors) == 1:
            raise errors[0]
        elif errors:
            raise MultipleValidationErrors(morphology['name'], errors)

    @classmethod
    def _validate_commands(cls, morphology_name, key, commands, errors):
            for cmd_index, cmd in enumerate(commands):
                if not isinstance(cmd, basestring):
                    e = InvalidTypeError('%s[%d]' % (key, cmd_index),
                                         str, type(cmd), morphology_name)
                    errors.append(e)

    @classmethod
    def _validate_products(cls, morphology_name, products, errors):
        '''Validate the products field is of the correct type.'''
        if (not isinstance(products, collections.Iterable)
            or isinstance(products, collections.Mapping)):
            raise InvalidTypeError('products', list,
                                   type(products), morphology_name)

        for spec_index, spec in enumerate(products):

            if not isinstance(spec, collections.Mapping):
                e = InvalidTypeError('products[%d]' % spec_index,
                                     dict, type(spec), morphology_name)
                errors.append(e)
                continue

            cls._validate_products_spec_fields_exist(morphology_name,
                                                     spec_index, spec, errors)

            if 'include' in spec:
                cls._validate_products_specs_include(
                    morphology_name, spec_index, spec['include'], errors)

    product_spec_required_fields = ('artifact', 'include')
    @classmethod
    def _validate_products_spec_fields_exist(
        cls, morphology_name, spec_index, spec, errors):

        given_fields = sorted(spec.iterkeys())
        missing = (field for field in cls.product_spec_required_fields
                   if field not in given_fields)
        for field in missing:
            e = MissingFieldError('products[%d].%s' % (spec_index, field),
                                  morphology_name)
            errors.append(e)
        unexpected = (field for field in given_fields
                      if field not in cls.product_spec_required_fields)
        for field in unexpected:
            e = InvalidFieldError('products[%d].%s' % (spec_index, field),
                                  morphology_name)
            errors.append(e)

    @classmethod
    def _validate_products_specs_include(cls, morphology_name, spec_index,
                                         include_patterns, errors):
        '''Validate that products' include field is a list of strings.'''
        # Allow include to be most iterables, but not a mapping
        # or a string, since iter of a mapping is just the keys,
        # and the iter of a string is a 1 character length string,
        # which would also validate as an iterable of strings.
        if (not isinstance(include_patterns, collections.Iterable)
            or isinstance(include_patterns, collections.Mapping)
            or isinstance(include_patterns, basestring)):

            e = InvalidTypeError('products[%d].include' % spec_index, list,
                                 type(include_patterns), morphology_name)
            errors.append(e)
        else:
            for pattern_index, pattern in enumerate(include_patterns):
                pattern_path = ('products[%d].include[%d]' %
                                (spec_index, pattern_index))
                if not isinstance(pattern, basestring):
                    e = InvalidTypeError(pattern_path, str,
                                         type(pattern), morphology_name)
                    errors.append(e)

    def _require_field(self, field, morphology):
        if field not in morphology:
            raise MissingFieldError(field, morphology.filename)

    def _require_fields(self, fields, morphology):
        for field in fields:
            self._require_field(field, morphology)

    def _deny_unknown_fields(self, allowed, morphology):
        for field in morphology:
            if field not in allowed:
                raise InvalidFieldError(field, morphology.filename)

    def set_defaults(self, morphology):
        '''Set all missing fields in the morpholoy to their defaults.

        The morphology is assumed to be valid.

        '''

        kind = morphology['kind']
        defaults = self._static_defaults[kind]
        for key in defaults:
            if key not in morphology:
                morphology[key] = defaults[key]

        getattr(self, '_set_%s_defaults' % kind)(morphology)

    def _set_cluster_defaults(self, morph):
        for system in morph.get('systems', []):
            if 'deploy-defaults' not in system:
                system['deploy-defaults'] = {}
            if 'deploy' not in system:
                system['deploy'] = {}

    def _set_system_defaults(self, morph):
        pass

    def _set_stratum_defaults(self, morph):
        for spec in morph['chunks']:
            if 'repo' not in spec:
                spec['repo'] = spec['name']
            if 'build-mode' not in spec:
                spec['build-mode'] = \
                    self._static_defaults['chunk']['build-mode']
            if 'prefix' not in spec:
                spec['prefix'] = \
                    self._static_defaults['chunk']['prefix']

    def _set_chunk_defaults(self, morph):
        if morph['max-jobs'] is not None:
            morph['max-jobs'] = int(morph['max-jobs'])

    def lookup_build_system(self, name):
        return self._predefined_build_systems[name]

    def set_commands(self, morph):
        if morph['kind'] == 'chunk':
            default = self._static_defaults['chunk']['build-system']
            bs_name = morph.get('build-system', default)

            try:
                bs = self.lookup_build_system(bs_name)
            except KeyError:
                raise UnknownBuildSystemError(bs_name, morph['name'])

            for key in self._static_defaults['chunk']:
                if 'commands' not in key: continue
                if key not in morph:
                    attr = '_'.join(key.split('-'))
                    morph[key] = getattr(bs, attr)
