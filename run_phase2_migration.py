#!/usr/bin/env python3
"""
Phase 2 Migration: Add encryption to Boswell
1. Run schema changes
2. Generate DEK for tenant
3. Migrate existing blobs
4. Export DEK backup
"""

import os
import sys
import psycopg2
import base64
from getpass import getpass

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from encryption_service import (
    EncryptionService,
    export_dek_backup,
    get_encryption_service
)

# Configuration
POSTGRES_URL = "postgresql://postgres:TZZuQAjZiJZPwHojTDhwchCZmNVPbNXY@gondola.proxy.rlwy.net:13404/railway?sslmode=require"
DEFAULT_TENANT = '00000000-0000-0000-0000-000000000001'
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), 'service-account-key.json')


def run_schema_migration(conn):
    """Run the Phase 2 schema changes"""
    print("\n[1/4] Running schema migration...")

    cur = conn.cursor()

    statements = [
        # DEK table
        (
            "Create data_encryption_keys table",
            """CREATE TABLE IF NOT EXISTS data_encryption_keys (
                key_id VARCHAR(64) PRIMARY KEY,
                tenant_id UUID REFERENCES tenants(id) DEFAULT '00000000-0000-0000-0000-000000000001',
                wrapped_key BYTEA NOT NULL,
                kms_key_version VARCHAR(255),
                algorithm VARCHAR(50) DEFAULT 'AES-256-GCM',
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                rotated_at TIMESTAMPTZ
            )"""
        ),
        ("Create DEK tenant index", "CREATE INDEX IF NOT EXISTS idx_dek_tenant ON data_encryption_keys(tenant_id)"),
        ("Create DEK status index", "CREATE INDEX IF NOT EXISTS idx_dek_status ON data_encryption_keys(status)"),

        # Blobs encryption columns
        ("Add content_encrypted to blobs", "ALTER TABLE blobs ADD COLUMN IF NOT EXISTS content_encrypted BYTEA"),
        ("Add nonce to blobs", "ALTER TABLE blobs ADD COLUMN IF NOT EXISTS nonce BYTEA"),
        ("Add encryption_key_id to blobs", "ALTER TABLE blobs ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(64)"),

        # Sessions encryption columns
        ("Add content_encrypted to sessions", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS content_encrypted BYTEA"),
        ("Add summary_encrypted to sessions", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary_encrypted BYTEA"),
        ("Add nonce to sessions", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS nonce BYTEA"),
        ("Add encryption_key_id to sessions", "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(64)"),
    ]

    for desc, sql in statements:
        print(f"  {desc}...", end=" ")
        try:
            cur.execute(sql)
            print("OK")
        except Exception as e:
            print(f"SKIP ({e})")

    conn.commit()
    cur.close()
    print("  Schema migration complete!")


def generate_tenant_dek(conn, encryption_service):
    """Generate a DEK for the default tenant"""
    print("\n[2/4] Generating Data Encryption Key...")

    cur = conn.cursor()

    # Check if DEK already exists
    cur.execute(
        "SELECT key_id FROM data_encryption_keys WHERE tenant_id = %s AND status = 'active'",
        (DEFAULT_TENANT,)
    )
    existing = cur.fetchone()
    if existing:
        print(f"  Active DEK already exists: {existing[0]}")
        cur.close()
        return existing[0]

    # Generate new DEK
    key_id, wrapped_dek, _ = encryption_service.generate_dek()

    # Store wrapped DEK in database
    cur.execute(
        """INSERT INTO data_encryption_keys (key_id, tenant_id, wrapped_key, status)
           VALUES (%s, %s, %s, 'active')""",
        (key_id, DEFAULT_TENANT, psycopg2.Binary(wrapped_dek))
    )
    conn.commit()
    cur.close()

    print(f"  Generated DEK: {key_id}")
    return key_id


def migrate_blobs(conn, encryption_service, key_id):
    """Migrate existing unencrypted blobs to encrypted format"""
    print("\n[3/4] Migrating existing blobs...")

    cur = conn.cursor()

    # Get the wrapped DEK
    cur.execute("SELECT wrapped_key FROM data_encryption_keys WHERE key_id = %s", (key_id,))
    wrapped_dek = bytes(cur.fetchone()[0])

    # Unwrap DEK
    plaintext_dek = encryption_service.unwrap_dek(key_id, wrapped_dek)

    # Find unencrypted blobs
    cur.execute(
        """SELECT blob_hash, content FROM blobs
           WHERE content IS NOT NULL AND content_encrypted IS NULL"""
    )
    blobs = cur.fetchall()

    if not blobs:
        print("  No unencrypted blobs found.")
        cur.close()
        return 0

    print(f"  Found {len(blobs)} blobs to encrypt...")
    migrated = 0

    for blob_hash, content in blobs:
        try:
            # Encrypt content
            ciphertext, nonce = encryption_service.encrypt(content, plaintext_dek)

            # Update blob
            cur.execute(
                """UPDATE blobs
                   SET content_encrypted = %s, nonce = %s, encryption_key_id = %s
                   WHERE blob_hash = %s""",
                (psycopg2.Binary(ciphertext), psycopg2.Binary(nonce), key_id, blob_hash)
            )
            migrated += 1

            if migrated % 100 == 0:
                print(f"    Migrated {migrated}/{len(blobs)}...")
                conn.commit()

        except Exception as e:
            print(f"  ERROR on {blob_hash[:8]}: {e}")

    conn.commit()
    cur.close()
    print(f"  Migrated {migrated} blobs successfully!")
    return migrated


def export_dek_backup_to_file(conn, key_id, passphrase):
    """Export DEK backup encrypted with passphrase"""
    print("\n[4/4] Exporting DEK backup...")

    cur = conn.cursor()
    cur.execute("SELECT wrapped_key FROM data_encryption_keys WHERE key_id = %s", (key_id,))
    wrapped_dek = bytes(cur.fetchone()[0])
    cur.close()

    # Create backup
    backup_data = export_dek_backup(wrapped_dek, passphrase)
    backup_b64 = base64.b64encode(backup_data).decode()

    # Save to file
    backup_path = os.path.join(os.path.dirname(__file__), f'dek_backup_{key_id}.txt')
    with open(backup_path, 'w') as f:
        f.write(f"# Boswell DEK Backup\n")
        f.write(f"# Key ID: {key_id}\n")
        f.write(f"# IMPORTANT: Store this file securely offline!\n")
        f.write(f"# You will need the passphrase to restore.\n\n")
        f.write(backup_b64)

    print(f"  Backup saved to: {backup_path}")
    print("  *** STORE THIS FILE SECURELY OFFLINE ***")


def verify_migration(conn):
    """Verify migration was successful"""
    print("\n=== VERIFICATION ===")
    cur = conn.cursor()

    # Check unencrypted blobs
    cur.execute("SELECT COUNT(*) FROM blobs WHERE content IS NOT NULL AND content_encrypted IS NULL")
    unencrypted = cur.fetchone()[0]
    print(f"Unencrypted blobs remaining: {unencrypted}")

    # Check encrypted blobs
    cur.execute("SELECT COUNT(*) FROM blobs WHERE content_encrypted IS NOT NULL")
    encrypted = cur.fetchone()[0]
    print(f"Encrypted blobs: {encrypted}")

    # Check DEKs
    cur.execute("SELECT COUNT(*) FROM data_encryption_keys WHERE status = 'active'")
    active_keys = cur.fetchone()[0]
    print(f"Active DEKs: {active_keys}")

    cur.close()

    if unencrypted == 0 and encrypted > 0:
        print("\n*** MIGRATION SUCCESSFUL ***")
        print("You can now safely run: ALTER TABLE blobs DROP COLUMN content;")
    else:
        print("\n*** MIGRATION INCOMPLETE ***")
        print("Some blobs still need encryption.")


def main():
    print("=" * 60)
    print("BOSWELL PHASE 2: ENCRYPTION MIGRATION")
    print("=" * 60)

    # Check credentials file
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"ERROR: Service account key not found at {CREDENTIALS_PATH}")
        sys.exit(1)

    print(f"\nUsing credentials: {CREDENTIALS_PATH}")

    # Get backup passphrase from env var or interactive input
    passphrase = os.environ.get('DEK_BACKUP_PASSPHRASE')

    if passphrase:
        print("\nUsing passphrase from DEK_BACKUP_PASSPHRASE environment variable")
    else:
        print("\nYou will need to set a passphrase for the DEK backup.")
        print("This is used for disaster recovery - REMEMBER THIS PASSPHRASE!")
        print("(Or set DEK_BACKUP_PASSPHRASE env var)")
        passphrase = getpass("Enter backup passphrase: ")
        passphrase_confirm = getpass("Confirm passphrase: ")

        if passphrase != passphrase_confirm:
            print("ERROR: Passphrases do not match!")
            sys.exit(1)

    if len(passphrase) < 12:
        print("ERROR: Passphrase must be at least 12 characters!")
        sys.exit(1)

    # Initialize encryption service
    print("\nInitializing encryption service...")
    encryption_service = get_encryption_service(CREDENTIALS_PATH)
    print("  KMS client initialized!")

    # Connect to Postgres
    print("\nConnecting to Postgres...")
    conn = psycopg2.connect(POSTGRES_URL)
    conn.autocommit = False
    print("  Connected!")

    # Set tenant context
    cur = conn.cursor()
    cur.execute(f"SET app.current_tenant = '{DEFAULT_TENANT}'")
    cur.close()

    try:
        # Run migration steps
        run_schema_migration(conn)
        key_id = generate_tenant_dek(conn, encryption_service)
        migrate_blobs(conn, encryption_service, key_id)
        export_dek_backup_to_file(conn, key_id, passphrase)

        # Verify
        verify_migration(conn)

    except Exception as e:
        print(f"\nERROR: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
        print("\nConnection closed.")


if __name__ == '__main__':
    main()
