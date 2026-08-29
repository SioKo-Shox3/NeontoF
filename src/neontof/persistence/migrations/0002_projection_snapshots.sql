CREATE TABLE projection_snapshots (
    campaign_id TEXT PRIMARY KEY,
    through_sequence INTEGER NOT NULL CHECK (through_sequence >= 0),
    projection_json BLOB NOT NULL CHECK (typeof(projection_json) = 'blob')
);
