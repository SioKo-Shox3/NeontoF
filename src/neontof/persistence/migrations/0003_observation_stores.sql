CREATE TABLE transcript_entries (
    campaign_id TEXT NOT NULL,
    append_sequence INTEGER NOT NULL CHECK (append_sequence > 0),
    entry_id TEXT NOT NULL,
    session_id TEXT NULL,
    turn_id TEXT NULL,
    model_call_id TEXT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'player_input', 'model_request', 'model_response', 'narrative',
            'error', 'retry', 'correction', 'tool_call'
        )
    ),
    occurred_at TEXT NOT NULL,
    data_json BLOB NOT NULL CHECK (typeof(data_json) = 'blob'),
    PRIMARY KEY (campaign_id, append_sequence),
    UNIQUE (entry_id)
);

CREATE TABLE telemetry_entries (
    campaign_id TEXT NOT NULL,
    append_sequence INTEGER NOT NULL CHECK (append_sequence > 0),
    entry_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    model_call_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    roles_json BLOB NOT NULL CHECK (typeof(roles_json) = 'blob'),
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status TEXT NOT NULL CHECK (
        status IN ('succeeded', 'failed', 'timed_out', 'rejected')
    ),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    cached_tokens INTEGER NOT NULL CHECK (cached_tokens >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    cost_microusd INTEGER NOT NULL CHECK (cost_microusd >= 0),
    error_code TEXT NULL,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, append_sequence),
    UNIQUE (entry_id)
);
