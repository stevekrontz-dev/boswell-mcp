#!/usr/bin/env python3
"""
Boswell v3 Migration - Add pgvector support for semantic search.

This script:
1. Enables pgvector extension
2. Adds embedding column to blobs table
3. Creates HNSW index for fast similarity search
4. Adds embedding_status column for async tracking

Run from local machine with DATABASE_URL set.
"""

import os
import sys
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    print("Set it with: export DATABASE_URL='postgresql://...'")
    sys.exit(1)

def run_migration():
    """Run the v3 schema migration."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    print("[V3 MIGRATION] Starting Boswell v3 vector-native migration...")

    # Step 1: Enable pgvector extension
    print("[1/4] Enabling pgvector extension...")
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("      pgvector extension enabled")
    except Exception as e:
        print(f"      WARNING: {e}")

    # Step 2: Add embedding column (nullable, 1536 dimensions for OpenAI)
    print("[2/4] Adding embedding column to blobs table...")
    try:
        cur.execute("""
            ALTER TABLE blobs
            ADD COLUMN IF NOT EXISTS embedding vector(1536);
        """)
        print("      embedding column added (vector(1536))")
    except Exception as e:
        print(f"      WARNING: {e}")

    # Step 3: Add embedding_status for async tracking
    print("[3/4] Adding embedding_status column...")
    try:
        cur.execute("""
            ALTER TABLE blobs
            ADD COLUMN IF NOT EXISTS embedding_status VARCHAR(20) DEFAULT 'pending';
        """)
        print("      embedding_status column added")
    except Exception as e:
        print(f"      WARNING: {e}")

    # Step 4: Create HNSW index
    print("[4/4] Creating HNSW index on embedding column...")
    try:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS blobs_embedding_hnsw_idx
            ON blobs USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """)
        print("      HNSW index created (m=16, ef_construction=64)")
    except Exception as e:
        print(f"      WARNING: {e}")

    # Verify
    print("\n[VERIFICATION] Checking schema...")
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'blobs'
        AND column_name IN ('embedding', 'embedding_status')
        ORDER BY column_name;
    """)
    columns = cur.fetchall()
    for col in columns:
        print(f"      {col[0]}: {col[1]}")

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'blobs' AND indexname LIKE '%embedding%';
    """)
    indexes = cur.fetchall()
    for idx in indexes:
        print(f"      index: {idx[0]}")

    cur.close()
    conn.close()

    print("\n[V3 MIGRATION] Complete! Schema ready for semantic search.")
    print("Next steps:")
    print("  1. Run backfill_embeddings.py to embed existing blobs")
    print("  2. Deploy updated app.py with async embedding")
    print("  3. Test /v2/search?mode=semantic")

if __name__ == '__main__':
    run_migration()
