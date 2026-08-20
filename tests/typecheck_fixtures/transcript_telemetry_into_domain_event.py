"""意図的に失敗するmypy fixture。通常qualityからは除外する。"""

from neontof.contracts.domain import TelemetryEntry, TranscriptEntry
from neontof.contracts.projection import rebuild_projection


def typed_sink(transcript_entry: TranscriptEntry, telemetry_entry: TelemetryEntry) -> None:
    """Transcript / TelemetryをDomainEventへ渡せないことを型検査する。"""

    rebuild_projection((transcript_entry,))
    rebuild_projection((telemetry_entry,))
