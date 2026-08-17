-- Run only for databases created from an older schema.
ALTER TABLE batches ADD COLUMN replacements_used INTEGER DEFAULT 0;
ALTER TABLE batches ADD COLUMN status TEXT DEFAULT 'active';
CREATE INDEX IF NOT EXISTS ix_batches_uid_status ON batches(uid,status);
CREATE INDEX IF NOT EXISTS ix_health_cfg_created ON health_checks(config_id,created);
CREATE INDEX IF NOT EXISTS ix_events_type_created ON events(type,created);
