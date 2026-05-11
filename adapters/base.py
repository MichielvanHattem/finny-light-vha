"""SourceAdapter-contract — uniforme base voor alle data-bron-pluggables.

ChatGPT-correctie 10 mei 2026:
- "Adapter-resultaten zonder uniforme bronkwaliteit" = serieus risico.
- Daarom: één SourceQuality-model dat ALLE adapters terug moeten geven.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class SourceFreshness(str, Enum):
    LIVE = "live"                     # MCP-API, real-time
    RECENT = "recent"                 # CSV-export <30 dagen oud
    HISTORICAL = "historical"         # Jaarrekening-PDF, XAF-auditfile
    STALE = "stale"                   # >90 dagen oud


@dataclass(frozen=True)
class UniformSourceQuality:
    """Uniform bronkwaliteit-model — verplicht in elke SourceResult.

    ChatGPT-correctie: NORMALISEER naar dit model. Geen losse 'confidence' uit
    elke adapter; centraal hier de waarheid.
    """
    source_available: bool                          # Adapter kon bron bereiken
    source_complete: bool                            # Bron dekt de gevraagde periode/post
    source_structured: bool                          # Output is parsable (geen ruis)
    period_coverage: tuple[date, date] | None        # (van, tot) — None als bron datum-loos is
    extraction_confidence: float                     # 0.0–1.0, post-extractie betrouwbaarheid
    freshness: SourceFreshness
    traceability: str                                # Waar komt deze data fysiek vandaan? (bv. "MCP/REST e-Boekhouden")
    cross_checked: bool = False                      # Cross-validated met tweede bron?
    notes: tuple[str, ...] = field(default_factory=tuple)

    def is_high_quality(self) -> bool:
        return (
            self.source_available
            and self.source_complete
            and self.source_structured
            and self.extraction_confidence >= 0.85
            and self.freshness in (SourceFreshness.LIVE, SourceFreshness.RECENT, SourceFreshness.HISTORICAL)
        )


@dataclass(frozen=True)
class AdapterHealth:
    ok: bool
    message: str
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class SourceQuery:
    """Een vraag voor een adapter. Generic over alle bron-types."""
    period_from: date | None
    period_to: date | None
    intent: str                                      # 'revenue', 'costs', 'balance', etc.
    raw_question: str                                # Voor logging
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceResult:
    """Wat een adapter teruggeeft. Genormaliseerd."""
    source_id: str                                   # 'mcp_eboekhouden:vha2:2026'
    source_type: str                                 # SourceType.value
    period: tuple[date, date] | None
    retrieved_at: datetime
    quality: UniformSourceQuality
    raw_reference: str                               # URL/path/endpoint
    normalized_payload: dict[str, Any]               # Adapter-specifieke data, gecanoniseerd

    def is_empty(self) -> bool:
        return not self.normalized_payload


class SourceAdapter(ABC):
    """Contract dat elke data-bron-pluggable implementeert."""

    NAME: str = "abstract"
    VERSION: str = "0.0.0"
    CAPABILITIES: tuple[str, ...] = ()                # Welke profile-capabilities deze adapter levert

    @abstractmethod
    def __init__(self, secrets: dict[str, str]) -> None:
        """Initialiseren met credentials uit Streamlit Secrets."""
        ...

    @abstractmethod
    def healthcheck(self) -> AdapterHealth:
        """Snel check: zijn credentials geldig en is de bron bereikbaar?"""
        ...

    @abstractmethod
    def retrieve(self, query: SourceQuery) -> SourceResult:
        """Haal data op voor de query. Faalt expliciet bij niet-haalbaar."""
        ...
