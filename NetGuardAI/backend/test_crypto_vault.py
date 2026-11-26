import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import crypto_vault as vault


class CryptoVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keys = Path(self.tmp.name)
        vault.generate_keys(self.keys)

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        token = vault.encrypt("ClaveSNMP-123", self.keys)
        self.assertTrue(token.startswith("enc:v1:"))
        self.assertNotIn("ClaveSNMP", token)
        self.assertEqual(vault.decrypt(token, self.keys), "ClaveSNMP-123")

    def test_each_encryption_is_different(self):
        self.assertNotEqual(vault.encrypt("x", self.keys), vault.encrypt("x", self.keys))

    def test_other_private_key_cannot_decrypt(self):
        token = vault.encrypt("secreto", self.keys)
        with tempfile.TemporaryDirectory() as other:
            vault.generate_keys(Path(other))
            with self.assertRaises(vault.VaultError):
                vault.decrypt(token, Path(other))

    def test_tampered_token_is_rejected(self):
        token = vault.encrypt("secreto", self.keys)
        broken = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
        with self.assertRaises(vault.VaultError):
            vault.decrypt(broken, self.keys)

    def test_reveal_plain_and_encrypted(self):
        self.assertEqual(vault.reveal("plano", self.keys), "plano")
        self.assertEqual(vault.reveal(vault.encrypt("z", self.keys), self.keys), "z")

    def test_passphrase_protected_private_key(self):
        with tempfile.TemporaryDirectory() as other, mock.patch.dict(
            os.environ, {"NETGUARD_KEY_PASSPHRASE": "frase-segura"}
        ):
            vault.generate_keys(Path(other))
            token = vault.encrypt("p", Path(other))
            self.assertEqual(vault.decrypt(token, Path(other)), "p")
            self.assertIn(b"ENCRYPTED", (Path(other) / vault.PRIVATE_KEY_FILE).read_bytes())

    def test_status_has_no_secrets(self):
        info = vault.status(self.keys)
        self.assertTrue(info["keysReady"])
        self.assertIn("RSA-2048", info["algorithm"])


if __name__ == "__main__":
    unittest.main()
