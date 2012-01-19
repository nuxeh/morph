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


import unittest

import morphlib


class BlobsTests(unittest.TestCase):

    def test_blob_with_parents(self):
        blob1 = morphlib.blobs.Blob(None)
        blob2 = morphlib.blobs.Blob(None)
        blob3 = morphlib.blobs.Blob(None)

        assert(len(blob1.parents) == 0)

        blob1.add_parent(blob2)
        assert(blob2 in blob1.parents)
        assert(blob3 not in blob1.parents)
        assert(len(blob1.parents) == 1)

        blob1.add_parent(blob3)
        assert(blob2 in blob1.parents)
        assert(blob3 in blob1.parents)
        assert(len(blob1.parents) == 2)

        blob1.remove_parent(blob2)
        assert(blob2 not in blob1.parents)
        assert(blob3 in blob1.parents)
        assert(len(blob1.parents) == 1)

        blob1.remove_parent(blob3)
        assert(blob2 not in blob1.parents)
        assert(blob3 not in blob1.parents)
        assert(len(blob1.parents) == 0)

    def test_blob_add_remove_dependency(self):
        blob1 = morphlib.blobs.Blob(None)
        blob2 = morphlib.blobs.Blob(None)

        assert(len(blob1.dependencies) == 0)
        assert(len(blob2.dependencies) == 0)

        blob1.add_dependency(blob2)

        assert(blob2 in blob1.dependencies)
        assert(blob1 in blob2.dependents)
        
        assert(blob1.depends_on(blob2))

        blob2.add_dependency(blob1)

        assert(blob2 in blob1.dependencies)
        assert(blob1 in blob2.dependents)
        assert(blob1 in blob2.dependencies)
        assert(blob2 in blob1.dependents)

        assert(blob1.depends_on(blob2))
        assert(blob2.depends_on(blob1))

        blob1.remove_dependency(blob2)

        assert(blob2 not in blob1.dependencies)
        assert(blob1 not in blob2.dependents)
        assert(blob1 in blob2.dependencies)
        assert(blob2 in blob1.dependents)

        assert(not blob1.depends_on(blob2))
        assert(blob2.depends_on(blob1))

        blob2.remove_dependency(blob1)

        assert(blob2 not in blob1.dependencies)
        assert(blob1 not in blob2.dependents)
        assert(blob1 not in blob2.dependencies)
        assert(blob2 not in blob1.dependents)

        assert(not blob1.depends_on(blob2))
        assert(not blob2.depends_on(blob1))

    def test_chunks(self):
        settings = { 'git-base-url': '' }
        loader = morphlib.morphologyloader.MorphologyLoader(settings)
        loader._get_morph_text = self.get_morph_text
        
        stratum_morph = loader.load('repo', 'ref', 'foo.morph')
        stratum = morphlib.blobs.Stratum(stratum_morph)
        assert(len(stratum.chunks) == 1)
        assert('foo' in stratum.chunks)
        self.assertEqual(['.'], stratum.chunks['foo'])

        chunk_morph = loader.load('repo', 'ref', 'bar.morph')
        chunk = morphlib.blobs.Chunk(chunk_morph)
        assert(len(chunk.chunks) == 2)
        assert('include' in chunk.chunks)
        self.assertEqual(chunk.chunks['include'], ['include/'])
        assert('src' in chunk.chunks)
        self.assertEqual(chunk.chunks['src'], ['src/'])

    def get_morph_text(self, repo, ref, filename):
        if filename == 'foo.morph':
            return ('''
                    {
                        "name": "foo",
                        "kind": "stratum",
                        "sources": [
                            {
                                "name": "bar",
                                "repo": "bar",
                                "ref": "master"
                            }
                        ]
                    }''')
        else:
            return ('''
                    {
                        "name": "bar",
                        "kind": "chunk",
                        "chunks": {
                            "include": [ "include/" ],
                            "src": [ "src/" ]
                        }
                    }''')
