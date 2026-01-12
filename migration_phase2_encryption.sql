-- PHASE 2: ENCRYPTION MIGRATION
-- Safe migration path: Add new columns → migrate → verify → drop old
-- Run this AFTER Phase 1 (Postgres multi-tenant) is complete

-- PART 1: DATA ENCRYPTION KEYS TABLE
-- Stores wrapped DEKs (encrypted by KMS master key)
CREATE TABLE IF NOT EXISTS data_encryption_keys (
  key_id VARCHAR(64) PRIMARY KEY,
  tenant_id UUID REFERENCES tenants(id) DEFAULT '00000000-0000-0000-0000-000000000001',
  wrapped_key BYTEA NOT NULL,           -- DEK encrypted by KMS master key
  kms_key_version VARCHAR(255),         -- Which KMS key version was used
  algorithm VARCHAR(50) DEFAULT 'AES-256-GCM',
  status VARCHAR(20) DEFAULT 'active',  -- active, rotating, retired
  created_at TIMESTAMPTZ DEFAULT NOW(),
  rotated_at TIMESTAMPTZ
);

CREATE INDEX idx_dek_tenant ON data_encryption_keys(tenant_id);
CREATE INDEX idx_dek_status ON data_encryption_keys(status);

-- Enable RLS on DEK table
ALTER TABLE data_encryption_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON data_encryption_keys
  USING (tenant_id = current_setting('app.current_tenant', true)::uuid);

-- PART 2: ADD ENCRYPTION COLUMNS TO BLOBS TABLE
-- Keep original 'content' column during migration for safety
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS content_encrypted BYTEA;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS nonce BYTEA;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(64) REFERENCES data_encryption_keys(key_id);

-- PART 3: ADD ENCRYPTION COLUMNS TO SESSIONS TABLE
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS content_encrypted BYTEA;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary_encrypted BYTEA;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS nonce BYTEA;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(64) REFERENCES data_encryption_keys(key_id);

-- PART 4: VERIFICATION QUERIES
-- Run these after migration to verify data integrity:
-- SELECT COUNT(*) FROM blobs WHERE content IS NOT NULL AND content_encrypted IS NULL;
-- Should return 0 after migration complete

-- SELECT COUNT(*) FROM blobs WHERE content_encrypted IS NOT NULL;
-- Should match total blob count after migration

-- PART 5: POST-MIGRATION CLEANUP (RUN ONLY AFTER VERIFICATION)
-- DANGER: Only run these after confirming all data is encrypted and verified!
-- ALTER TABLE blobs DROP COLUMN content;
-- ALTER TABLE sessions DROP COLUMN content;
-- ALTER TABLE sessions DROP COLUMN summary;
