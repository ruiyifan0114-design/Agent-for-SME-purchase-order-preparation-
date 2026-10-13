from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from backend.domain.intake import read_files


@dataclass(frozen=True)
class SourceEnvelope:
    dataset: dict
    source_system: str
    external_id: str | None = None
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class ProcurementSourceAdapter(Protocol):
    def fetch(self) -> SourceEnvelope: ...


class CSVAdapter:
    def __init__(self, files: list[tuple[str, bytes]], external_id: str | None = None):
        self.files, self.external_id = files, external_id

    def fetch(self) -> SourceEnvelope:
        return SourceEnvelope(read_files(self.files), "csv", self.external_id,
                              metadata={"filenames": [name for name, _ in self.files]})


class JSONAdapter:
    def __init__(self, dataset: dict, external_id: str | None = None, source_system: str = "json"):
        self.dataset, self.external_id, self.source_system = dataset, external_id, source_system

    def fetch(self) -> SourceEnvelope:
        return SourceEnvelope(self.dataset, self.source_system, self.external_id)


class MockERPAdapter(JSONAdapter):
    def __init__(self, dataset: dict, external_id: str = "demo-erp-snapshot"):
        super().__init__(dataset, external_id, "mock_erp")
