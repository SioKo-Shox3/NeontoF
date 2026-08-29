CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL CHECK (
        length(checksum_sha256) = 64
        AND checksum_sha256 = lower(checksum_sha256)
        AND checksum_sha256 NOT GLOB '*[^0-9a-f]*'
    )
);

CREATE TABLE events (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_id TEXT NOT NULL,
    type TEXT NOT NULL,
    event_version INTEGER NOT NULL CHECK (event_version = 1),
    session_id TEXT NULL,
    scene_id TEXT NULL,
    turn_id TEXT NULL,
    occurred_at TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('in_world', 'table_correction')),
    visibility TEXT NOT NULL,
    event_json BLOB NOT NULL CHECK (typeof(event_json) = 'blob'),
    PRIMARY KEY (campaign_id, sequence),
    UNIQUE (event_id)
);
