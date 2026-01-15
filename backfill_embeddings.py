#!/usr/bin/env python3
"""
Boswell v3 Backfill - Embed existing blobs using OpenAI.

This script:
1. Fetches all blobs without embeddings
2. Generates embeddings via OpenAI text-embedding-3-small
3. Updates blobs with embeddings

Run from local machine with DATABASE_URL and OPENAI_API_KEY set.
"""

import os
import sys
import json
import psycopg2
import psycopg2.extras
from openai import OpenAI

DATABASE_URL = os.environ.get('DATABASE_URL')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    sys.exit(1)

if not OPENAI_API_KEY:
    print("ERROR: OPENAI_API_KEY environment variable not set")
    sys.exit(1)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def get_embedding(text: str) -> list[float]:
    """Generate embedding for text using OpenAI."""
    # Truncate if too long (max 8191 tokens for text-embedding-3-small)
    if len(text) > 30000:
        text = text[:30000]

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
        dimensions=1536
    )
    return response.data[0].embedding

def run_backfill():
    """Backfill embeddings for all blobs."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("[BACKFILL] Fetching blobs without embeddings...")
    cur.execute("""
        SELECT blob_hash, content
        FROM blobs
        WHERE embedding IS NULL
        ORDER BY created_at DESC;
    """)
    blobs = cur.fetchall()
    print(f"[BACKFILL] Found {len(blobs)} blobs to embed")

    if len(blobs) == 0:
        print("[BACKFILL] Nothing to do!")
        return

    success = 0
    failed = 0

    for i, blob in enumerate(blobs):
        blob_hash = blob['blob_hash']
        content = blob['content']

        try:
            # Generate embedding
            embedding = get_embedding(content)

            # Update blob with embedding
            cur.execute("""
                UPDATE blobs
                SET embedding = %s::vector, embedding_status = 'complete'
                WHERE blob_hash = %s;
            """, (embedding, blob_hash))
            conn.commit()

            success += 1
            print(f"[{i+1}/{len(blobs)}] Embedded {blob_hash[:12]}...")

        except Exception as e:
            failed += 1
            print(f"[{i+1}/{len(blobs)}] FAILED {blob_hash[:12]}: {e}")

            # Mark as failed
            cur.execute("""
                UPDATE blobs
                SET embedding_status = 'failed'
                WHERE blob_hash = %s;
            """, (blob_hash,))
            conn.commit()

    cur.close()
    conn.close()

    print(f"\n[BACKFILL] Complete!")
    print(f"  Success: {success}")
    print(f"  Failed:  {failed}")
    print(f"  Total:   {len(blobs)}")

if __name__ == '__main__':
    run_backfill()
