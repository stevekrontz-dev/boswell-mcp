"""
Boswell Encryption Service
Implements envelope encryption with Google Cloud KMS + AES-256-GCM
"""

import os
import hashlib
import secrets
import time
from typing import Optional, Tuple
from functools import lru_cache
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.cloud import kms

# Configuration
PROJECT_ID = "boswell-memory"
LOCATION = "global"
KEY_RING = "boswell-keyring"
KEY_NAME = "boswell-master-key"

# DEK cache with TTL (5 minutes)
DEK_CACHE_TTL = 300
_dek_cache = {}  # key_id -> (plaintext_dek, timestamp)


class EncryptionService:
    """Handles envelope encryption using KMS + AES-256-GCM"""

    def __init__(self, credentials_path: Optional[str] = None):
        """Initialize KMS client with service account credentials

        Supports:
        - credentials_path: path to JSON key file
        - GOOGLE_APPLICATION_CREDENTIALS_JSON env var: JSON string
        - GOOGLE_APPLICATION_CREDENTIALS env var: path to file
        """
        # Check for JSON credentials in env var (for Railway/cloud deployment)
        credentials_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')

        if credentials_json:
            # Parse JSON and create credentials object
            import json
            from google.oauth2 import service_account
            credentials_info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            self.kms_client = kms.KeyManagementServiceClient(credentials=credentials)
        elif credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            self.kms_client = kms.KeyManagementServiceClient()
        else:
            # Fall back to default credentials
            self.kms_client = kms.KeyManagementServiceClient()

        self.key_name = self.kms_client.crypto_key_path(
            PROJECT_ID, LOCATION, KEY_RING, KEY_NAME
        )

    def generate_dek(self) -> Tuple[str, bytes, bytes]:
        """
        Generate a new Data Encryption Key (DEK)
        Returns: (key_id, wrapped_dek, plaintext_dek)
        """
        # Generate 256-bit key
        plaintext_dek = secrets.token_bytes(32)

        # Generate key ID from hash
        key_id = hashlib.sha256(plaintext_dek + secrets.token_bytes(8)).hexdigest()[:16]

        # Wrap DEK using KMS master key
        encrypt_response = self.kms_client.encrypt(
            request={"name": self.key_name, "plaintext": plaintext_dek}
        )
        wrapped_dek = encrypt_response.ciphertext

        # Cache the plaintext DEK
        _dek_cache[key_id] = (plaintext_dek, time.time())

        return key_id, wrapped_dek, plaintext_dek

    def unwrap_dek(self, key_id: str, wrapped_dek: bytes) -> bytes:
        """
        Unwrap a DEK using KMS master key
        Uses cache if available and not expired
        """
        # Check cache first
        if key_id in _dek_cache:
            plaintext_dek, cached_at = _dek_cache[key_id]
            if time.time() - cached_at < DEK_CACHE_TTL:
                return plaintext_dek

        # Decrypt using KMS
        decrypt_response = self.kms_client.decrypt(
            request={"name": self.key_name, "ciphertext": wrapped_dek}
        )
        plaintext_dek = decrypt_response.plaintext

        # Update cache
        _dek_cache[key_id] = (plaintext_dek, time.time())

        return plaintext_dek

    def encrypt(self, plaintext: str, dek: bytes) -> Tuple[bytes, bytes]:
        """
        Encrypt content using AES-256-GCM
        Returns: (ciphertext, nonce)
        """
        # Generate random 96-bit nonce
        nonce = secrets.token_bytes(12)

        # Encrypt
        aesgcm = AESGCM(dek)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes, dek: bytes) -> str:
        """
        Decrypt content using AES-256-GCM
        Returns: plaintext string
        """
        aesgcm = AESGCM(dek)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')

    def encrypt_with_new_dek(self, plaintext: str) -> Tuple[bytes, bytes, str, bytes]:
        """
        Encrypt content with a newly generated DEK
        Returns: (ciphertext, nonce, key_id, wrapped_dek)
        """
        key_id, wrapped_dek, plaintext_dek = self.generate_dek()
        ciphertext, nonce = self.encrypt(plaintext, plaintext_dek)
        return ciphertext, nonce, key_id, wrapped_dek

    def decrypt_with_wrapped_dek(
        self, ciphertext: bytes, nonce: bytes, key_id: str, wrapped_dek: bytes
    ) -> str:
        """
        Decrypt content using a wrapped DEK
        """
        plaintext_dek = self.unwrap_dek(key_id, wrapped_dek)
        return self.decrypt(ciphertext, nonce, plaintext_dek)

    @staticmethod
    def clear_dek_cache():
        """Clear the DEK cache (useful for testing or rotation)"""
        _dek_cache.clear()

    @staticmethod
    def get_cache_stats() -> dict:
        """Get DEK cache statistics"""
        now = time.time()
        active = sum(1 for _, (_, ts) in _dek_cache.items() if now - ts < DEK_CACHE_TTL)
        return {
            "total_cached": len(_dek_cache),
            "active": active,
            "expired": len(_dek_cache) - active,
            "ttl_seconds": DEK_CACHE_TTL
        }


def export_dek_backup(wrapped_dek: bytes, passphrase: str) -> bytes:
    """
    Export a wrapped DEK with additional passphrase protection
    For disaster recovery - store offline securely
    """
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    # Derive key from passphrase
    salt = secrets.token_bytes(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,  # High iteration count for security
    )
    passphrase_key = kdf.derive(passphrase.encode())

    # Encrypt wrapped DEK with passphrase-derived key
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(passphrase_key)
    encrypted = aesgcm.encrypt(nonce, wrapped_dek, None)

    # Return salt + nonce + encrypted data
    return salt + nonce + encrypted


def import_dek_backup(backup_data: bytes, passphrase: str) -> bytes:
    """
    Import a DEK from passphrase-protected backup
    """
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    # Extract salt, nonce, and encrypted data
    salt = backup_data[:16]
    nonce = backup_data[16:28]
    encrypted = backup_data[28:]

    # Derive key from passphrase
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    passphrase_key = kdf.derive(passphrase.encode())

    # Decrypt wrapped DEK
    aesgcm = AESGCM(passphrase_key)
    wrapped_dek = aesgcm.decrypt(nonce, encrypted, None)

    return wrapped_dek


# Singleton instance for the app
_service_instance: Optional[EncryptionService] = None

def get_encryption_service(credentials_path: Optional[str] = None) -> EncryptionService:
    """Get or create the singleton encryption service"""
    global _service_instance
    if _service_instance is None:
        _service_instance = EncryptionService(credentials_path)
    return _service_instance
