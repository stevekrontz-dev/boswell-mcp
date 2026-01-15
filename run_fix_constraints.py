#!/usr/bin/env python3
"""
Fix missing unique constraints in Boswell database.
Run from local machine with DATABASE_URL set.
"""

import os
import sys
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    sys.exit(1)

def run_migration():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    print("[FIX CONSTRAINTS] Starting...")

    # Check current constraints
    print("\n[1/4] Checking current blobs constraints...")
    cur.execute("""
        SELECT constraint_name, constraint_type
        FROM information_schema.table_constraints
        WHERE table_name = 'blobs' AND constraint_type IN ('PRIMARY KEY', 'UNIQUE');
    """)
    for row in cur.fetchall():
        print(f"      {row[0]}: {row[1]}")

    # Fix blobs: change PK to composite
    print("\n[2/4] Fixing blobs table primary key...")
    try:
        # Drop existing PK
        cur.execute("ALTER TABLE blobs DROP CONSTRAINT IF EXISTS blobs_pkey CASCADE;")
        # Add composite PK
        cur.execute("ALTER TABLE blobs ADD PRIMARY KEY (tenant_id, blob_hash);")
        print("      Changed PK to (tenant_id, blob_hash)")
    except Exception as e:
        print(f"      ERROR: {e}")
        # Rollback and try alternative approach
        conn.rollback()
        try:
            # Maybe PK has different name, try adding unique constraint instead
            cur.execute("ALTER TABLE blobs ADD CONSTRAINT blobs_tenant_hash_unique UNIQUE (tenant_id, blob_hash);")
            print("      Added UNIQUE(tenant_id, blob_hash) constraint")
        except Exception as e2:
            print(f"      ERROR on fallback: {e2}")

    # Check current tags constraints
    print("\n[3/4] Checking current tags constraints...")
    cur.execute("""
        SELECT constraint_name, constraint_type
        FROM information_schema.table_constraints
        WHERE table_name = 'tags' AND constraint_type IN ('PRIMARY KEY', 'UNIQUE');
    """)
    for row in cur.fetchall():
        print(f"      {row[0]}: {row[1]}")

    # Fix tags: add correct unique constraint
    print("\n[4/4] Fixing tags table unique constraint...")
    try:
        # Drop the wrong constraint
        cur.execute("ALTER TABLE tags DROP CONSTRAINT IF EXISTS tags_tenant_id_name_key;")
        # Add correct constraint
        cur.execute("ALTER TABLE tags ADD CONSTRAINT tags_tenant_blob_tag_unique UNIQUE (tenant_id, blob_hash, tag);")
        print("      Added UNIQUE(tenant_id, blob_hash, tag) constraint")
    except Exception as e:
        print(f"      ERROR: {e}")

    # Verify
    print("\n[VERIFICATION]")
    cur.execute("""
        SELECT table_name, constraint_name, constraint_type
        FROM information_schema.table_constraints
        WHERE table_name IN ('blobs', 'tags') AND constraint_type IN ('PRIMARY KEY', 'UNIQUE')
        ORDER BY table_name, constraint_name;
    """)
    for row in cur.fetchall():
        print(f"      {row[0]}.{row[1]}: {row[2]}")

    cur.close()
    conn.close()
    print("\n[FIX CONSTRAINTS] Done!")

if __name__ == '__main__':
    run_migration()
