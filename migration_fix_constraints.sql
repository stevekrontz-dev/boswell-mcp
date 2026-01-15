-- FIX UNIQUE CONSTRAINTS FOR ON CONFLICT CLAUSES
-- The code uses ON CONFLICT (tenant_id, blob_hash) but only PRIMARY KEY(blob_hash) exists
-- Run this to add the missing constraints

-- Fix blobs table: Add composite unique constraint
-- First drop the primary key, then add composite unique
-- NOTE: This is tricky because blob_hash is the PK
-- Instead, add a unique constraint on the composite (blob_hash is already unique via PK,
-- but we need the composite for ON CONFLICT)
ALTER TABLE blobs DROP CONSTRAINT IF EXISTS blobs_pkey CASCADE;
ALTER TABLE blobs ADD PRIMARY KEY (tenant_id, blob_hash);

-- Fix tags table: Add correct composite unique constraint
-- Current: UNIQUE(tenant_id, name) -- wrong column
-- Needed: UNIQUE(tenant_id, blob_hash, tag)
ALTER TABLE tags DROP CONSTRAINT IF EXISTS tags_tenant_id_name_key;
ALTER TABLE tags ADD CONSTRAINT tags_tenant_blob_tag_unique UNIQUE (tenant_id, blob_hash, tag);
