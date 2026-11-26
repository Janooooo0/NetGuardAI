"""Bóveda de secretos con cifrado asimétrico (RSA) para NetGuard AI.

Idea, explicada de forma sencilla
---------------------------------
* Se genera un par de llaves RSA-2048:
  - la llave **pública** sirve para *cerrar el candado* (cifrar). Puede compartirse;
  - la llave **privada** es la única que *abre el candado* (descifrar). Nunca sale
    del servidor y no se sube a GitHub (carpeta ``keys/`` en ``.gitignore``).
* Como RSA solo puede cifrar mensajes cortos, se usa el esquema **híbrido**
  estándar (el mismo principio que usan TLS/HTTPS y PGP):
  1. se crea una llave AES-256 aleatoria de un solo uso;
  2. el texto se cifra con AES-256-GCM (rápido y detecta alteraciones);
  3. la llave AES se cifra con la llave pública RSA (relleno OAEP + SHA-256).
* Resultado: un texto ``enc:v1:...`` que puede guardarse en ``.env`` o en la
  configuración sin exponer la clave real. Solo el servidor con la llave
  privada puede recuperarla.

Uso desde la terminal (en la raíz del proyecto)::

    python backend/crypto_vault.py generar
    python backend/crypto_vault.py cifrar "MiClaveSNMP123"
    python backend/crypto_vault.py descifrar "enc:v1:..."
    python backend/crypto_vault.py estado
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

PREFIX = "enc:v1:"
KEYS_DIR = Path(
    os.environ.get("NETGUARD_KEYS_DIR")
    or Path(__file__).resolve().parent.parent / "keys"
)
PRIVATE_KEY_FILE = "netguard_private.pem"
PUBLIC_KEY_FILE = "netguard_public.pem"


class VaultError(RuntimeError):
    pass


def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as error:  # pragma: no cover
        raise VaultError(
            "Instala la dependencia 'cryptography' (pip install -r requirements.txt)."
        ) from error
    return hashes, serialization, padding, rsa, AESGCM


def _passphrase() -> bytes | None:
    value = os.environ.get("NETGUARD_KEY_PASSPHRASE")
    return value.encode() if value else None


def generate_keys(keys_dir: Path = KEYS_DIR, *, overwrite: bool = False) -> Path:
    """Crea el par de llaves RSA-2048. La privada puede protegerse con frase."""
    _, serialization, _, rsa, _ = _crypto()
    keys_dir.mkdir(parents=True, exist_ok=True)
    private_path = keys_dir / PRIVATE_KEY_FILE
    if private_path.exists() and not overwrite:
        raise VaultError(f"Ya existe {private_path}; no se sobrescribe.")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    passphrase = _passphrase()
    encryption = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase
        else serialization.NoEncryption()
    )
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            encryption,
        )
    )
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    (keys_dir / PUBLIC_KEY_FILE).write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return keys_dir


def _load_public(keys_dir: Path):
    _, serialization, _, _, _ = _crypto()
    path = keys_dir / PUBLIC_KEY_FILE
    if not path.exists():
        raise VaultError(
            "No hay llave pública. Ejecuta: python backend/crypto_vault.py generar"
        )
    return serialization.load_pem_public_key(path.read_bytes())


def _load_private(keys_dir: Path):
    _, serialization, _, _, _ = _crypto()
    path = keys_dir / PRIVATE_KEY_FILE
    if not path.exists():
        raise VaultError("No se encontró la llave privada para descifrar secretos.")
    try:
        return serialization.load_pem_private_key(path.read_bytes(), _passphrase())
    except (TypeError, ValueError) as error:
        raise VaultError("No se pudo abrir la llave privada (¿frase incorrecta?).") from error


def _oaep():
    hashes, _, padding, _, _ = _crypto()
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    )


def encrypt(text: str, keys_dir: Path = KEYS_DIR) -> str:
    """Cifra ``text`` con el esquema híbrido RSA-OAEP + AES-256-GCM."""
    *_, AESGCM = _crypto()
    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, text.encode("utf-8"), None)
    wrapped_key = _load_public(keys_dir).encrypt(aes_key, _oaep())
    payload = {
        "k": base64.b64encode(wrapped_key).decode(),
        "n": base64.b64encode(nonce).decode(),
        "c": base64.b64encode(ciphertext).decode(),
    }
    return PREFIX + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decrypt(token: str, keys_dir: Path = KEYS_DIR) -> str:
    *_, AESGCM = _crypto()
    if not token.startswith(PREFIX):
        raise VaultError("El valor no tiene el formato enc:v1:")
    try:
        payload = json.loads(base64.urlsafe_b64decode(token[len(PREFIX):]))
        wrapped_key = base64.b64decode(payload["k"])
        nonce = base64.b64decode(payload["n"])
        ciphertext = base64.b64decode(payload["c"])
    except (ValueError, KeyError, TypeError) as error:
        raise VaultError("Secreto cifrado mal formado.") from error
    try:
        aes_key = _load_private(keys_dir).decrypt(wrapped_key, _oaep())
        return AESGCM(aes_key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except VaultError:
        raise
    except Exception as error:
        raise VaultError(
            "No se pudo descifrar: llave incorrecta o dato alterado."
        ) from error


def reveal(value: str, keys_dir: Path = KEYS_DIR) -> str:
    """Devuelve el valor tal cual o lo descifra si empieza por ``enc:v1:``."""
    return decrypt(value, keys_dir) if value.startswith(PREFIX) else value


def status(keys_dir: Path = KEYS_DIR) -> dict:
    """Resumen público (sin secretos) del estado de la bóveda."""
    public_path = keys_dir / PUBLIC_KEY_FILE
    info = {
        "algorithm": "RSA-2048 OAEP/SHA-256 + AES-256-GCM (híbrido)",
        "snmpTransport": "SNMPv3 authPriv (SHA/SHA-256 + AES-128)",
        "keysReady": public_path.exists() and (keys_dir / PRIVATE_KEY_FILE).exists(),
        "publicKeyFingerprint": None,
    }
    if public_path.exists():
        digest = hashlib.sha256(public_path.read_bytes()).hexdigest()
        info["publicKeyFingerprint"] = ":".join(
            digest[i : i + 2] for i in range(0, 32, 2)
        )
    return info


def _main(argv: list[str]) -> int:
    usage = "Uso: crypto_vault.py generar | cifrar TEXTO | descifrar TOKEN | estado"
    if not argv:
        print(usage)
        return 1
    command, *rest = argv
    try:
        if command == "generar":
            print(f"Llaves RSA-2048 creadas en {generate_keys()}")
        elif command == "cifrar" and rest:
            print(encrypt(rest[0]))
        elif command == "descifrar" and rest:
            print(decrypt(rest[0]))
        elif command == "estado":
            print(json.dumps(status(), indent=2, ensure_ascii=False))
        else:
            print(usage)
            return 1
    except VaultError as error:
        print(f"Error: {error}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
