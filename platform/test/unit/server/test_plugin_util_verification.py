# -*- coding: utf-8 -*-
# Copyright (c) 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

from cStringIO import StringIO
import hashlib
import unittest

from pulp.plugins.util import verification


class VerificationTests(unittest.TestCase):

    def test_size(self):
        # Setup
        expected_size = 9
        test_file = StringIO('Test data')

        # Test
        valid, found_size = verification.verify_size(test_file, expected_size)

        # Verify
        self.assertTrue(valid)
        self.assertEqual(found_size, expected_size)

    def test_size_incorrect(self):
        # Setup
        expected_size = 9
        test_file = StringIO('Test data')

        # Test
        valid, found_size = verification.verify_size(test_file, 1)

        # Verify
        self.assertTrue(not valid)
        self.assertEqual(found_size, expected_size)

    def test_checksum_sha256(self):
        # Setup
        test_file = StringIO('Test data')
        expected_checksum = 'e27c8214be8b7cf5bccc7c08247e3cb0c1514a48ee1f63197fe4ef3ef51d7e6f'

        # Test
        valid, found_checksum = verification.verify_checksum(test_file, verification.TYPE_SHA256,
                                                             expected_checksum)

        # Verify
        self.assertTrue(valid)
        self.assertEqual(found_checksum, expected_checksum)

    def test_checksum_sha256_incorrect(self):
        # Setup
        test_file = StringIO('Test data')
        expected_checksum = 'e27c8214be8b7cf5bccc7c08247e3cb0c1514a48ee1f63197fe4ef3ef51d7e6f'

        # Test
        valid, found_checksum = verification.verify_checksum(test_file, verification.TYPE_SHA256,
                                                             'foo')

        # Verify
        self.assertTrue(not valid)
        self.assertEqual(found_checksum, expected_checksum)

    def test_checksum_invalid_checksum(self):
        self.assertRaises(ValueError, verification.verify_checksum,
                          StringIO(), 'fake-type', 'irrelevant')

    def test_checksum_algorithm_mappings(self):
        self.assertEqual(3, len(verification.CHECKSUM_FUNCTIONS))
        self.assertEqual(verification.CHECKSUM_FUNCTIONS[verification.TYPE_MD5], hashlib.md5)
        self.assertEqual(verification.CHECKSUM_FUNCTIONS[verification.TYPE_SHA1], hashlib.sha1)
        self.assertEqual(verification.CHECKSUM_FUNCTIONS[verification.TYPE_SHA256], hashlib.sha256)
