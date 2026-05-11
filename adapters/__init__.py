"""Adapters — data-bron-pluggables.

ChatGPT-correctie 10 mei 2026:
- Elke adapter implementeert hetzelfde SourceAdapter-contract.
- Niet-enabled adapters worden NIET top-level geïmporteerd (lazy via source_loader).
- Resultaten normaliseren naar één SourceQuality-model — geen rommel uit losse adapters.
"""
from .base import (
    SourceAdapter,
    SourceQuery,
    SourceResult,
    AdapterHealth,
    UniformSourceQuality,
    SourceFreshness,
)

__all__ = [
    "SourceAdapter",
    "SourceQuery",
    "SourceResult",
    "AdapterHealth",
    "UniformSourceQuality",
    "SourceFreshness",
]
