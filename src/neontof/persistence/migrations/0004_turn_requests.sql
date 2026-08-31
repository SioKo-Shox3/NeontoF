CREATE TABLE turn_requests (
    request_key BLOB NOT NULL PRIMARY KEY CHECK (
        typeof(request_key) = 'blob'
        AND length(request_key) BETWEEN 1 AND 256
    ),
    request_kind TEXT NOT NULL CHECK (
        typeof(request_kind) = 'text'
        AND request_kind IN ('submit', 'resume')
    ),
    requested_media_type TEXT NOT NULL CHECK (
        typeof(requested_media_type) = 'text'
        AND requested_media_type IN ('application/json', 'text/event-stream')
    ),
    turn_request_id TEXT NOT NULL CHECK (
        typeof(turn_request_id) = 'text'
        AND length(turn_request_id) > 0
    ),
    campaign_id TEXT NOT NULL CHECK (
        typeof(campaign_id) = 'text'
        AND length(campaign_id) > 0
    ),
    session_id TEXT NOT NULL CHECK (
        typeof(session_id) = 'text'
        AND length(session_id) > 0
    ),
    scene_id TEXT NOT NULL CHECK (
        typeof(scene_id) = 'text'
        AND length(scene_id) > 0
    ),
    turn_id TEXT NOT NULL CHECK (
        typeof(turn_id) = 'text'
        AND length(turn_id) > 0
    ),
    root_turn_request_id TEXT NOT NULL CHECK (
        typeof(root_turn_request_id) = 'text'
        AND length(root_turn_request_id) > 0
    ),
    input_digest TEXT NOT NULL CHECK (
        typeof(input_digest) = 'text'
        AND length(input_digest) > 0
    ),
    base_event_sequence INTEGER NOT NULL CHECK (
        typeof(base_event_sequence) = 'integer'
        AND base_event_sequence >= 0
    ),
    status TEXT NOT NULL CHECK (
        typeof(status) = 'text'
        AND status IN ('processing', 'awaiting_player', 'committed', 'aborted')
    ),
    recovery_reason TEXT NULL CHECK (
        recovery_reason IS NULL
        OR (
            typeof(recovery_reason) = 'text'
            AND recovery_reason IN (
            'claim_before_first_event',
            'after_player_input_accepted',
            'after_turn_resumed',
            'after_turn_awaiting_player',
            'after_terminal'
            )
        )
    ),
    recovery_selector TEXT NULL CHECK (
        recovery_selector IS NULL
        OR (
            typeof(recovery_selector) = 'text'
            AND recovery_selector IN (
                'no_lifecycle_events',
                'accepted_without_terminal',
                'resumed_without_terminal',
                'awaiting_player',
                'terminal'
            )
        )
    ),
    accepted_event_id TEXT NULL CHECK (
        accepted_event_id IS NULL
        OR (
            typeof(accepted_event_id) = 'text'
            AND length(accepted_event_id) > 0
        )
    ),
    resumed_event_id TEXT NULL CHECK (
        resumed_event_id IS NULL
        OR (
            typeof(resumed_event_id) = 'text'
            AND length(resumed_event_id) > 0
        )
    ),
    awaiting_player_event_id TEXT NULL CHECK (
        awaiting_player_event_id IS NULL
        OR (
            typeof(awaiting_player_event_id) = 'text'
            AND length(awaiting_player_event_id) > 0
        )
    ),
    committed_event_id TEXT NULL CHECK (
        committed_event_id IS NULL
        OR (
            typeof(committed_event_id) = 'text'
            AND length(committed_event_id) > 0
        )
    ),
    aborted_event_id TEXT NULL CHECK (
        aborted_event_id IS NULL
        OR (
            typeof(aborted_event_id) = 'text'
            AND length(aborted_event_id) > 0
        )
    ),
    recovery_aborted_event_id TEXT NULL CHECK (
        recovery_aborted_event_id IS NULL
        OR (
            typeof(recovery_aborted_event_id) = 'text'
            AND length(recovery_aborted_event_id) > 0
        )
    ),
    occurred_at TEXT NULL CHECK (
        occurred_at IS NULL
        OR (
            typeof(occurred_at) = 'text'
            AND length(occurred_at) > 0
        )
    ),
    initial_recovery_payload BLOB NOT NULL CHECK (
        typeof(initial_recovery_payload) = 'blob'
        AND length(initial_recovery_payload) > 0
    ),
    staged_recovery_payload BLOB NULL CHECK (
        staged_recovery_payload IS NULL
        OR (
            typeof(staged_recovery_payload) = 'blob'
            AND length(staged_recovery_payload) > 0
        )
    ),
    recovery_payload_version INTEGER NOT NULL CHECK (
        typeof(recovery_payload_version) = 'integer'
        AND (
        (
            recovery_payload_version = 1
            AND staged_recovery_payload IS NULL
        )
        OR (
            recovery_payload_version = 2
            AND staged_recovery_payload IS NOT NULL
        )
        )
    ),
    response_status_code INTEGER NULL CHECK (
        response_status_code IS NULL
        OR (
            typeof(response_status_code) = 'integer'
            AND response_status_code = 200
        )
    ),
    response_media_type TEXT NULL CHECK (
        response_media_type IS NULL
        OR (
            typeof(response_media_type) = 'text'
            AND response_media_type = requested_media_type
        )
    ),
    response_body BLOB NULL CHECK (
        response_body IS NULL
        OR (
            typeof(response_body) = 'blob'
            AND length(response_body) > 0
        )
    ),
    CHECK (
        (
            recovery_reason IS NULL
            AND recovery_selector IS NULL
            AND accepted_event_id IS NULL
            AND resumed_event_id IS NULL
            AND awaiting_player_event_id IS NULL
            AND committed_event_id IS NULL
            AND aborted_event_id IS NULL
            AND recovery_aborted_event_id IS NULL
            AND occurred_at IS NULL
        )
        OR (
            recovery_reason IS NOT NULL
            AND recovery_selector IS NOT NULL
            AND occurred_at IS NOT NULL
        )
    ),
    CHECK (
        (
            status = 'processing'
            AND response_status_code IS NULL
            AND response_media_type IS NULL
            AND response_body IS NULL
        )
        OR (
            status IN ('awaiting_player', 'committed', 'aborted')
            AND typeof(response_status_code) = 'integer'
            AND response_status_code = 200
            AND typeof(response_media_type) = 'text'
            AND response_media_type = requested_media_type
            AND typeof(response_body) = 'blob'
            AND length(response_body) > 0
        )
    )
);

CREATE UNIQUE INDEX uq_turn_requests_campaign_processing
    ON turn_requests (campaign_id)
    WHERE status = 'processing';

CREATE INDEX idx_turn_requests_campaign_turn_request_id
    ON turn_requests (campaign_id, turn_request_id);
