"""意図的に失敗するmypy fixture。通常qualityからは除外する。"""

from typing import assert_type


class DomainEvent:
    """ゲーム状態へ入るEventの最小test-only型。"""


class TranscriptEntry:
    """状態EventではないTranscript型。"""


class TelemetryEntry:
    """状態EventではないTelemetry型。"""


def append_domain_event(event: DomainEvent) -> None:
    """DomainEventだけを受ける最小境界。"""

    del event


transcript_entry = TranscriptEntry()
telemetry_entry = TelemetryEntry()

assert_type(transcript_entry, DomainEvent)
append_domain_event(transcript_entry)  # type: ignore[arg-type]
assert_type(telemetry_entry, DomainEvent)
append_domain_event(telemetry_entry)  # type: ignore[arg-type]
