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
import unittest

import morphlib


class FakeCacheKeyComputer(object):
    '''Fake computer that uses the uppercase source name as the cache key.'''

    def compute_key(self, source):
        return source.morphology['name'].upper()


class FakeChunkMorphology(morphlib.morph2.Morphology):

    def __init__(self, name, artifact_names=[]):
        assert(isinstance(artifact_names, list))

        if artifact_names:
            # fake a list of artifacts
            artifacts = {}
            for artifact_name in artifact_names:
                artifacts[artifact_name] = [artifact_name]
            text = ('''
                    {
                        "name": "%s",
                        "kind": "chunk",
                        "chunks": %s
                    }
                    ''' % (name, json.dumps(artifacts)))
        else:
            text = ('''
                    {
                        "name": "%s",
                        "kind": "chunk"
                    }
                    ''' % name)
        morphlib.morph2.Morphology.__init__(self, text)


class FakeStratumMorphology(morphlib.morph2.Morphology):

    def __init__(self, name, source_list=[], build_depends=[]):
        assert(isinstance(source_list, list))
        assert(isinstance(build_depends, list))

        if source_list:
            sources = []
            for source_name, morph, repo, ref in source_list:
                sources.append({
                    'name': source_name,
                    'morph': morph,
                    'repo': repo,
                    'ref': ref
                })
            text = ('''
                    {
                        "name": "%s",
                        "kind": "stratum",
                        "build-depends": %s,
                        "sources": %s
                    }
                    ''' % (name,
                           json.dumps(build_depends),
                           json.dumps(sources)))
        else:
            text = ('''
                    {
                        "name": "%s",
                        "kind": "stratum",
                        "build-depends": %s
                    }
                    ''' % (name,
                           json.dumps(build_depends)))
        morphlib.morph2.Morphology.__init__(self, text)


class ArtifactResolverTests(unittest.TestCase):

    def setUp(self):
        self.repo = morphlib.cachedrepo.CachedRepo(
                'repo', 'git://foo.bar/repo.git', '/foo/bar/repo')
        self.cache_key_computer = FakeCacheKeyComputer()
        self.resolver = morphlib.artifactresolver.ArtifactResolver(
                self.cache_key_computer)

    def test_resolve_artifacts_using_an_empty_pool(self):
        pool = morphlib.sourcepool.SourcePool()
        artifacts = self.resolver.resolve_artifacts(pool)
        self.assertEqual(len(artifacts), 0)

    def test_resolve_single_chunk_with_no_subartifacts(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk')
        source = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(source)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 1)

        self.assertEqual(artifacts[0].source, source)
        self.assertEqual(artifacts[0].name, 'chunk')
        self.assertEqual(artifacts[0].cache_key, 'CHUNK')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [])

    def test_resolve_single_chunk_with_one_artifact(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk', ['chunk-runtime'])
        source = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(source)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].source, source)
        self.assertEqual(artifacts[0].name, 'chunk-runtime')
        self.assertEqual(artifacts[0].cache_key, 'CHUNK')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [])

    def test_resolve_single_chunk_with_two_artifact(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk', ['chunk-runtime', 'chunk-devel'])
        source = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(source)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 2)

        self.assertEqual(artifacts[0].source, source)
        self.assertEqual(artifacts[0].name, 'chunk-devel')
        self.assertEqual(artifacts[0].cache_key, 'CHUNK')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, source)
        self.assertEqual(artifacts[1].name, 'chunk-runtime')
        self.assertEqual(artifacts[1].cache_key, 'CHUNK')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents, [])

    def test_resolve_a_single_empty_stratum(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "foo",
                    "kind": "stratum"
                }
                ''')
        stratum = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'foo.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'foo')
        self.assertEqual(artifacts[0].cache_key, 'FOO')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [])

    def test_resolve_a_single_empty_system(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "foo",
                    "kind": "system"
                }
                ''')
        system = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'foo.morph')
        pool.add(system)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(artifacts[0].source, system)
        self.assertEqual(artifacts[0].name, 'foo')
        self.assertEqual(artifacts[0].cache_key, 'FOO')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [])

    def test_resolve_stratum_and_chunk_with_no_subartifacts(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk')
        chunk = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(chunk)

        morph = FakeStratumMorphology(
                'stratum', [('chunk', 'chunk', 'repo', 'ref')])
        stratum = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 2)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'stratum')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM')
        self.assertEqual(artifacts[0].dependencies, [artifacts[1]])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, chunk)
        self.assertEqual(artifacts[1].name, 'chunk')
        self.assertEqual(artifacts[1].cache_key, 'CHUNK')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents, [artifacts[0]])

    def test_resolve_stratum_and_chunk_with_two_subartifacts(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk', ['chunk-devel', 'chunk-runtime'])
        chunk = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(chunk)

        morph = FakeStratumMorphology(
                'stratum', [
                    ('chunk-devel', 'chunk', 'repo', 'ref'),
                    ('chunk-runtime', 'chunk', 'repo', 'ref')
                ])
        stratum = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 3)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'stratum')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM')
        self.assertEqual(artifacts[0].dependencies,
                         [artifacts[1], artifacts[2]])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, chunk)
        self.assertEqual(artifacts[1].name, 'chunk-devel')
        self.assertEqual(artifacts[1].cache_key, 'CHUNK')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents, [artifacts[0], artifacts[2]])

        self.assertEqual(artifacts[2].source, chunk)
        self.assertEqual(artifacts[2].name, 'chunk-runtime')
        self.assertEqual(artifacts[2].cache_key, 'CHUNK')
        self.assertEqual(artifacts[2].dependencies, [artifacts[1]])
        self.assertEqual(artifacts[2].dependents, [artifacts[0]])

    def test_resolve_stratum_and_chunk_with_one_used_subartifacts(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk', ['chunk-devel', 'chunk-runtime'])
        chunk = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(chunk)

        morph = FakeStratumMorphology(
                'stratum', [
                    ('chunk-runtime', 'chunk', 'repo', 'ref')
                ])
        stratum = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 2)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'stratum')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM')
        self.assertEqual(artifacts[0].dependencies, [artifacts[1]])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, chunk)
        self.assertEqual(artifacts[1].name, 'chunk-runtime')
        self.assertEqual(artifacts[1].cache_key, 'CHUNK')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents, [artifacts[0]])

    def test_resolving_two_different_chunk_artifacts_in_a_stratum(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('foo')
        foo_chunk = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'foo.morph')
        pool.add(foo_chunk)

        morph = FakeChunkMorphology('bar')
        bar_chunk = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'bar.morph')
        pool.add(bar_chunk)

        morph = FakeStratumMorphology(
                'stratum', [
                    ('foo', 'foo', 'repo', 'ref'),
                    ('bar', 'bar', 'repo', 'ref')
                ])
        stratum = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 3)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'stratum')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM')
        self.assertEqual(artifacts[0].dependencies,
                         [artifacts[1], artifacts[2]])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, foo_chunk)
        self.assertEqual(artifacts[1].name, 'foo')
        self.assertEqual(artifacts[1].cache_key, 'FOO')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents, [artifacts[0], artifacts[2]])

        self.assertEqual(artifacts[2].source, bar_chunk)
        self.assertEqual(artifacts[2].name, 'bar')
        self.assertEqual(artifacts[2].cache_key, 'BAR')
        self.assertEqual(artifacts[2].dependencies, [artifacts[1]])
        self.assertEqual(artifacts[2].dependents, [artifacts[0]])

    def test_resolving_artifacts_for_a_chain_of_two_strata(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeStratumMorphology('stratum1')
        stratum1 = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum1.morph')
        pool.add(stratum1)

        morph = FakeStratumMorphology('stratum2', [], ['stratum1'])
        stratum2 = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum2.morph')
        pool.add(stratum2)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 2)

        self.assertEqual(artifacts[0].source, stratum1)
        self.assertEqual(artifacts[0].name, 'stratum1')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM1')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [artifacts[1]])

        self.assertEqual(artifacts[1].source, stratum2)
        self.assertEqual(artifacts[1].name, 'stratum2')
        self.assertEqual(artifacts[1].cache_key, 'STRATUM2')
        self.assertEqual(artifacts[1].dependencies, [artifacts[0]])
        self.assertEqual(artifacts[1].dependents, [])

    def test_resolving_with_a_stratum_and_chunk_dependency_mix(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = FakeStratumMorphology('stratum1')
        stratum1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum1.morph')
        pool.add(stratum1)

        morph = FakeStratumMorphology(
                'stratum2', [
                    ('chunk1', 'chunk1', 'repo', 'original/ref'),
                    ('chunk2', 'chunk2', 'repo', 'original/ref')
                ], ['stratum1'])
        stratum2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum2.morph')
        pool.add(stratum2)

        morph = FakeChunkMorphology('chunk1')
        chunk1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = FakeChunkMorphology('chunk2')
        chunk2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk2.morph')
        pool.add(chunk2)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 4)

        self.assertEqual(artifacts[0].source, stratum1)
        self.assertEqual(artifacts[0].name, 'stratum1')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM1')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents,
                        [artifacts[1], artifacts[2], artifacts[3]])

        self.assertEqual(artifacts[1].source, stratum2)
        self.assertEqual(artifacts[1].name, 'stratum2')
        self.assertEqual(artifacts[1].cache_key, 'STRATUM2')
        self.assertEqual(artifacts[1].dependencies,
                         [artifacts[0], artifacts[2], artifacts[3]])
        self.assertEqual(artifacts[1].dependents, [])
        
        self.assertEqual(artifacts[2].source, chunk1)
        self.assertEqual(artifacts[2].name, 'chunk1')
        self.assertEqual(artifacts[2].cache_key, 'CHUNK1')
        self.assertEqual(artifacts[2].dependencies, [artifacts[0]])
        self.assertEqual(artifacts[2].dependents, [artifacts[1], artifacts[3]])
        
        self.assertEqual(artifacts[3].source, chunk2)
        self.assertEqual(artifacts[3].name, 'chunk2')
        self.assertEqual(artifacts[3].cache_key, 'CHUNK2')
        self.assertEqual(artifacts[3].dependencies,
                         [artifacts[0], artifacts[2]])
        self.assertEqual(artifacts[3].dependents, [artifacts[1]])

    def test_resolving_artifacts_for_a_system_with_two_strata(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeStratumMorphology('stratum1')
        stratum1 = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum1.morph')
        pool.add(stratum1)

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "system",
                    "kind": "system",
                    "strata": [
                        "stratum1", 
                        "stratum2"
                    ]
                }
                ''')
        system = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'system.morph')
        pool.add(system)

        morph = FakeStratumMorphology('stratum2', [], ['stratum1'])
        stratum2 = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum2.morph')
        pool.add(stratum2)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 3)

        self.assertEqual(artifacts[0].source, stratum1)
        self.assertEqual(artifacts[0].name, 'stratum1')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM1')
        self.assertEqual(artifacts[0].dependencies, [])
        self.assertEqual(artifacts[0].dependents, [artifacts[1], artifacts[2]])

        self.assertEqual(artifacts[1].source, system)
        self.assertEqual(artifacts[1].name, 'system')
        self.assertEqual(artifacts[1].cache_key, 'SYSTEM')
        self.assertEqual(artifacts[1].dependencies,
                         [artifacts[0], artifacts[2]])
        self.assertEqual(artifacts[1].dependents, [])

        self.assertEqual(artifacts[2].source, stratum2)
        self.assertEqual(artifacts[2].name, 'stratum2')
        self.assertEqual(artifacts[2].cache_key, 'STRATUM2')
        self.assertEqual(artifacts[2].dependencies, [artifacts[0]])
        self.assertEqual(artifacts[2].dependents, [artifacts[1]])

    def test_resolving_stratum_with_explicit_chunk_dependencies(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "stratum",
                    "kind": "stratum",
                    "sources": [
                        {
                            "name": "chunk1",
                            "repo": "repo",
                            "ref": "original/ref",
                            "build-depends": []
                        },
                        {
                            "name": "chunk2",
                            "repo": "repo",
                            "ref": "original/ref",
                            "build-depends": []
                        },
                        {
                            "name": "chunk3",
                            "repo": "repo",
                            "ref": "original/ref",
                            "build-depends": [
                                "chunk1",
                                "chunk2"
                            ]
                        }
                    ]
                }
                ''')
        stratum = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        morph = FakeChunkMorphology('chunk1')
        chunk1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = FakeChunkMorphology('chunk2')
        chunk2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk2.morph')
        pool.add(chunk2)

        morph = FakeChunkMorphology('chunk3')
        chunk3 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk3.morph')
        pool.add(chunk3)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 4)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'stratum')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM')
        self.assertEqual(artifacts[0].dependencies,
                         [artifacts[1], artifacts[2], artifacts[3]])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, chunk1)
        self.assertEqual(artifacts[1].name, 'chunk1')
        self.assertEqual(artifacts[1].cache_key, 'CHUNK1')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents,
                         [artifacts[0], artifacts[3]])

        self.assertEqual(artifacts[2].source, chunk2)
        self.assertEqual(artifacts[2].name, 'chunk2')
        self.assertEqual(artifacts[2].cache_key, 'CHUNK2')
        self.assertEqual(artifacts[2].dependencies, [])
        self.assertEqual(artifacts[2].dependents, [artifacts[0], artifacts[3]])

        self.assertEqual(artifacts[3].source, chunk3)
        self.assertEqual(artifacts[3].name, 'chunk3')
        self.assertEqual(artifacts[3].cache_key, 'CHUNK3')
        self.assertEqual(artifacts[3].dependencies,
                         [artifacts[1], artifacts[2]])
        self.assertEqual(artifacts[3].dependents, [artifacts[0]])

    def test_detection_of_invalid_chunk_artifact_references(self):
        pool = morphlib.sourcepool.SourcePool()
        
        morph = FakeChunkMorphology('chunk')
        chunk = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'chunk.morph')
        pool.add(chunk)

        morph = FakeStratumMorphology(
                'stratum', [
                    ('chunk-runtime', 'chunk', 'repo', 'ref')
                ])
        stratum = morphlib.source.Source(
                self.repo, 'ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        self.assertRaises(
                morphlib.artifactresolver.UndefinedChunkArtifactError,
                self.resolver.resolve_artifacts, pool)

    def test_detection_of_mutual_dependency_between_two_strata(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = FakeStratumMorphology('stratum1', [], ['stratum2'])
        stratum1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum1.morph')
        pool.add(stratum1)

        morph = FakeStratumMorphology('stratum2', [], ['stratum1'])
        stratum2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum2.morph')
        pool.add(stratum2)

        self.assertRaises(morphlib.artifactresolver.MutualDependencyError,
                          self.resolver.resolve_artifacts, pool)

    def test_detection_of_mutual_dependency_between_consecutive_chunks(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = FakeStratumMorphology(
                'stratum1', [
                    ('chunk1', 'chunk1', 'repo', 'original/ref'),
                    ('chunk2', 'chunk2', 'repo', 'original/ref')
                ], [])
        stratum1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum1.morph')
        pool.add(stratum1)

        morph = FakeStratumMorphology(
                'stratum2', [
                    ('chunk2', 'chunk2', 'repo', 'original/ref'),
                    ('chunk1', 'chunk1', 'repo', 'original/ref')
                ], ['stratum1'])
        stratum2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum2.morph')
        pool.add(stratum2)

        morph = FakeChunkMorphology('chunk1')
        chunk1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = FakeChunkMorphology('chunk2')
        chunk2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk2.morph')
        pool.add(chunk2)

        self.assertRaises(morphlib.artifactresolver.MutualDependencyError,
                          self.resolver.resolve_artifacts, pool)

    def test_graceful_handling_of_self_dependencies_of_chunks(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "stratum",
                    "kind": "stratum",
                    "sources": [
                        {
                            "name": "chunk",
                            "repo": "repo",
                            "ref": "original/ref"
                        },
                        {
                            "name": "chunk",
                            "repo": "repo",
                            "ref": "original/ref"
                        },
                        {
                            "name": "chunk",
                            "repo": "repo",
                            "ref": "original/ref",
                            "build-depends": [
                                "chunk"
                            ]
                        }
                    ]
                }
                ''')
        stratum = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        morph = FakeChunkMorphology('chunk')
        chunk = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk.morph')
        pool.add(chunk)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts), 2)

        self.assertEqual(artifacts[0].source, stratum)
        self.assertEqual(artifacts[0].name, 'stratum')
        self.assertEqual(artifacts[0].cache_key, 'STRATUM')
        self.assertEqual(artifacts[0].dependencies, [artifacts[1]])
        self.assertEqual(artifacts[0].dependents, [])

        self.assertEqual(artifacts[1].source, chunk)
        self.assertEqual(artifacts[1].name, 'chunk')
        self.assertEqual(artifacts[1].cache_key, 'CHUNK')
        self.assertEqual(artifacts[1].dependencies, [])
        self.assertEqual(artifacts[1].dependents, [artifacts[0]])

    def test_detection_of_chunk_dependencies_in_invalid_order(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "stratum",
                    "kind": "stratum",
                    "sources": [
                        {
                            "name": "chunk1",
                            "repo": "repo",
                            "ref": "original/ref",
                            "build-depends": [
                                "chunk2"
                            ]
                        },
                        {
                            "name": "chunk2",
                            "repo": "repo",
                            "ref": "original/ref"
                        }
                    ]
                }
                ''')
        stratum = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        morph = FakeChunkMorphology('chunk1')
        chunk1 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = FakeChunkMorphology('chunk2')
        chunk2 = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk2.morph')
        pool.add(chunk2)

        self.assertRaises(morphlib.artifactresolver.DependencyOrderError,
                          self.resolver.resolve_artifacts, pool)

    def test_detection_of_invalid_build_depends_format(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = morphlib.morph2.Morphology(
                '''
                {
                    "name": "stratum",
                    "kind": "stratum",
                    "sources": [
                        {
                            "name": "chunk",
                            "repo": "repo",
                            "ref": "original/ref",
                            "build-depends": "whatever"
                        }
                    ]
                }
                ''')
        stratum = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'stratum.morph')
        pool.add(stratum)

        morph = FakeChunkMorphology('chunk')
        chunk = morphlib.source.Source(
                self.repo, 'original/ref', 'sha1', morph, 'chunk.morph')
        pool.add(chunk)

        self.assertRaises(morphlib.artifactresolver.DependencyFormatError,
                          self.resolver.resolve_artifacts, pool)
