"""Synthetic, network-free tests: python3 -m unittest -v test_envelope.py."""
import base64
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

import oauth_envelope as envelope


class EnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tau-envelope-synthetic-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.receiver = envelope.create_session(cls.root)
        cls.session = cls.receiver["session"]
        cls.public = cls.receiver["public_key_pem"]
        cls.credentials = {field: "synthetic-secret-for-" + field for field in envelope.FIELDS}
        # Exercise UTF-8 spanning several 400-byte chunks.
        cls.credentials["ALPACA_OAUTH_CLIENT_SECRET"] = "synthetic-" + "界" * 300
        cls.packet = envelope.encrypt_credentials(cls.public, cls.session, cls.credentials)

    @classmethod
    def tearDownClass(cls):
        envelope.destroy_session(cls.session, cls.root)
        cls.temporary.cleanup()

    def assert_rejected(self, fn, *args, **kwargs):
        with self.assertRaises(envelope.EnvelopeError) as result:
            fn(*args, **kwargs)
        self.assertEqual(str(result.exception), "Credential envelope operation failed.")

    def test_roundtrip_json_and_ciphertext_contains_no_plaintext(self):
        wire = json.dumps(self.packet)
        self.assertEqual(envelope.decrypt_credentials(self.session, json.loads(wire), self.root), self.credentials)
        for value in self.credentials.values():
            self.assertNotIn(value, wire)
        self.assertNotIn("PRIVATE KEY", wire)
        self.assertNotEqual(envelope.encrypt_credentials(self.public, self.session, self.credentials), self.packet)

    def test_ciphertext_tampering_is_rejected(self):
        packet = copy.deepcopy(self.packet)
        raw = bytearray(base64.b64decode(packet["fields"]["ALPACA_OAUTH_CLIENT_ID"][0]))
        raw[-1] ^= 1
        packet["fields"]["ALPACA_OAUTH_CLIENT_ID"][0] = base64.b64encode(raw).decode("ascii")
        self.assert_rejected(envelope.decrypt_credentials, self.session, packet, self.root)

    def test_field_swapping_is_rejected(self):
        packet = copy.deepcopy(self.packet)
        a, b = "ALPACA_OAUTH_CLIENT_ID", "ALPACA_OAUTH_CLIENT_SECRET"
        packet["fields"][a], packet["fields"][b] = packet["fields"][b], packet["fields"][a]
        self.assert_rejected(envelope.decrypt_credentials, self.session, packet, self.root)

    def test_chunk_reordering_and_truncation_are_rejected(self):
        packet = copy.deepcopy(self.packet)
        chunks = packet["fields"]["ALPACA_OAUTH_CLIENT_SECRET"]
        chunks[0], chunks[1] = chunks[1], chunks[0]
        self.assert_rejected(envelope.decrypt_credentials, self.session, packet, self.root)
        packet = copy.deepcopy(self.packet)
        packet["fields"]["ALPACA_OAUTH_CLIENT_SECRET"].pop()
        self.assert_rejected(envelope.decrypt_credentials, self.session, packet, self.root)

    def test_session_metadata_and_oaep_session_label_are_bound(self):
        other = "tau-provider-probe-" + "a" * 32
        self.assert_rejected(envelope.decrypt_credentials, other, self.packet, self.root)
        packet = envelope.encrypt_credentials(self.public, other, self.credentials)
        packet["session"] = self.session
        self.assert_rejected(envelope.decrypt_credentials, self.session, packet, self.root)

    def test_credential_fields_and_lengths_are_strict(self):
        for mutation in ("missing", "unknown", "empty", "non_string", "oversized"):
            credentials = dict(self.credentials)
            if mutation == "missing":
                credentials.pop("ALPACA_OAUTH_CLIENT_SECRET")
            elif mutation == "unknown":
                credentials["UNEXPECTED"] = "synthetic"
            elif mutation == "empty":
                credentials["ALPACA_OAUTH_CLIENT_SECRET"] = "   "
            elif mutation == "non_string":
                credentials["ALPACA_OAUTH_CLIENT_SECRET"] = 123
            else:
                credentials["ALPACA_OAUTH_CLIENT_SECRET"] = "x" * 4097
            with self.subTest(mutation=mutation):
                self.assert_rejected(envelope.encrypt_credentials, self.public, self.session, credentials)

    def test_malformed_and_huge_envelopes_are_rejected(self):
        for mutation in ("unknown", "missing", "version", "chunks", "large_chunk", "invalid_base64"):
            packet = copy.deepcopy(self.packet)
            if mutation == "unknown":
                packet["unknown"] = True
            elif mutation == "missing":
                packet["fields"].pop("ALPACA_OAUTH_CLIENT_SECRET")
            elif mutation == "version":
                packet["version"] = True
            elif mutation == "chunks":
                packet["fields"]["ALPACA_OAUTH_CLIENT_SECRET"] *= 1000
            elif mutation == "large_chunk":
                packet["fields"]["ALPACA_OAUTH_CLIENT_SECRET"] = ["x" * 100000]
            else:
                packet["fields"]["ALPACA_OAUTH_CLIENT_SECRET"][0] = "!" * 684
            with self.subTest(mutation=mutation):
                self.assert_rejected(envelope.decrypt_credentials, self.session, packet, self.root)

    def test_private_permissions_and_no_plaintext_files(self):
        directory = self.root / self.session
        key = directory / envelope.KEY_FILE
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertEqual(set(p.name for p in directory.iterdir()), {envelope.KEY_FILE})
        self.assertNotIn("PRIVATE KEY", self.public)
        os.chmod(key, 0o644)
        try:
            self.assert_rejected(envelope.decrypt_credentials, self.session, self.packet, self.root)
        finally:
            os.chmod(key, 0o600)

    def test_traversal_and_symlinks_are_rejected(self):
        self.assert_rejected(envelope.destroy_session, "../" + self.session, self.root)
        alias = self.root / "root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        try:
            self.assert_rejected(envelope.create_session, alias)
            self.assert_rejected(envelope.decrypt_credentials, self.session, self.packet, alias)
        finally:
            alias.unlink()
        alias_session = "tau-provider-probe-" + "b" * 32
        alias = self.root / alias_session
        alias.symlink_to(self.root / self.session, target_is_directory=True)
        packet = copy.deepcopy(self.packet)
        packet["session"] = alias_session
        try:
            self.assert_rejected(envelope.decrypt_credentials, alias_session, packet, self.root)
            self.assert_rejected(envelope.destroy_session, alias_session, self.root)
        finally:
            alias.unlink()

    def test_cleanup_removes_private_key_and_is_idempotent(self):
        receiver = envelope.create_session(self.root)
        directory = self.root / receiver["session"]
        self.assertTrue((directory / envelope.KEY_FILE).is_file())
        envelope.destroy_session(receiver["session"], self.root)
        self.assertFalse(directory.exists())
        envelope.destroy_session(receiver["session"], self.root)

    def test_private_key_symlink_cannot_be_read_or_removed(self):
        directory = self.root / self.session
        key = directory / envelope.KEY_FILE
        backup = directory / "synthetic-test-backup.pem"
        key.rename(backup)
        key.symlink_to(backup)
        try:
            self.assert_rejected(envelope.decrypt_credentials, self.session, self.packet, self.root)
            self.assert_rejected(envelope.destroy_session, self.session, self.root)
            self.assertTrue(backup.is_file())
        finally:
            key.unlink()
            backup.rename(key)


if __name__ == "__main__":
    unittest.main()
