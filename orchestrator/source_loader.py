"""SourceLoader — laadt alleen enabled adapters, fail-fast bij inconsistentie.

ChatGPT-eindadvies 10 mei 2026:
- adapter registry laadt alleen enabled adapters (lazy import)
- niet-enabled dependencies staan niet in de MCP-only image
- startup faalt als profiel adapter vraagt die niet geïnstalleerd is
- startup faalt als adapter credentials ontbreken
"""
from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from profiles.schema import Profile, SourceType

if TYPE_CHECKING:
    from adapters.base import SourceAdapter

logger = logging.getLogger(__name__)


# Adapter registry — module-pad + class-naam per SourceType.
# NIET top-level importeren (lazy loading): PDF/CSV/XAF-modules mogen ontbreken.
ADAPTER_REGISTRY: dict[SourceType, tuple[str, str]] = {
    SourceType.MCP_EBOEKHOUDEN: ("adapters.mcp_eboekhouden", "MCPEboekhoudenAdapter"),
    SourceType.CSV_EBOEKHOUDEN: ("adapters.csv_eboekhouden", "CSVEboekhoudenAdapter"),
    SourceType.PDF_JAARREKENING: ("adapters.pdf_jaarrekening", "PDFJaarrekeningAdapter"),
    SourceType.XAF: ("adapters.xaf", "XAFAdapter"),
}


class SourceLoaderError(RuntimeError):
    """Basisklasse voor loader-fouten."""


class InconsistentProfileError(SourceLoaderError):
    """Profiel belooft capability waarvoor geen actieve adapter bestaat."""


class AdapterImportError(SourceLoaderError):
    """Adapter staat in profiel maar module/class kan niet geïmporteerd worden."""


class AdapterCredentialsError(SourceLoaderError):
    """Adapter is geladen maar healthcheck faalt (credentials ontbreken/ongeldig)."""


class SourceLoader:
    """Houdt actieve adapters voor het huidige profiel.

    Standaard gebruik:
        loader = SourceLoader(profile, secrets={"EBOEKHOUDEN_TOKEN": "..."})
        loader.validate_or_raise()           # fail-fast bij startup
        adapter = loader.get(SourceType.MCP_EBOEKHOUDEN)
    """

    def __init__(self, profile: Profile, secrets: dict[str, str] | None = None) -> None:
        self.profile = profile
        self.secrets = secrets or {}
        self._adapters: dict[SourceType, "SourceAdapter"] = {}

    # --------------------------------------------------------------- public

    def validate_or_raise(self) -> None:
        """Volledige fail-fast validatie. Roep aan bij startup vóór UI rendert."""
        self._import_enabled_adapters()
        self._healthcheck_all()
        self._verify_capability_consistency()
        logger.info(
            "SourceLoader OK — profiel=%s, adapters=%s",
            self.profile.profile_id,
            [s.value for s in self._adapters.keys()],
        )

    def get(self, source_type: SourceType) -> "SourceAdapter":
        """Haal actieve adapter op. Roept KeyError als niet enabled — bewust."""
        if source_type not in self._adapters:
            raise KeyError(
                f"Adapter '{source_type.value}' is niet enabled in profiel "
                f"'{self.profile.profile_id}'. Niet-enabled adapters mogen niet "
                f"runtime-stilletjes laden."
            )
        return self._adapters[source_type]

    def is_enabled(self, source_type: SourceType) -> bool:
        return source_type in self._adapters

    @property
    def active_sources(self) -> list[SourceType]:
        return list(self._adapters.keys())

    @property
    def adapter_versions(self) -> dict[str, str]:
        """Voor logging — welke adapter-versies draaien."""
        return {
            s.value: getattr(a, "VERSION", "unknown")
            for s, a in self._adapters.items()
        }

    # --------------------------------------------------------------- private

    def _import_enabled_adapters(self) -> None:
        for source_type in self.profile.enabled_sources:
            if source_type not in ADAPTER_REGISTRY:
                raise InconsistentProfileError(
                    f"SourceType '{source_type.value}' is enabled in profiel "
                    f"'{self.profile.profile_id}', maar bestaat niet in ADAPTER_REGISTRY. "
                    f"Voeg implementatie toe of verwijder uit profiel."
                )
            module_path, class_name = ADAPTER_REGISTRY[source_type]
            try:
                module = importlib.import_module(module_path)
            except ImportError as exc:
                raise AdapterImportError(
                    f"Profiel '{self.profile.profile_id}' enabled '{source_type.value}', "
                    f"maar module '{module_path}' kan niet geïmporteerd worden: {exc}. "
                    f"Installeer optionele dependencies: pip install -e '.[full]'"
                ) from exc
            cls = getattr(module, class_name, None)
            if cls is None:
                raise AdapterImportError(
                    f"Module '{module_path}' bevat geen class '{class_name}'."
                )
            try:
                adapter = cls(secrets=self.secrets)
            except Exception as exc:
                raise AdapterImportError(
                    f"Instantiëren van '{class_name}' faalt: {exc}"
                ) from exc
            self._adapters[source_type] = adapter

    def _healthcheck_all(self) -> None:
        failed: list[str] = []
        for source_type, adapter in self._adapters.items():
            try:
                health = adapter.healthcheck()
                if not health.ok:
                    failed.append(f"{source_type.value}: {health.message}")
            except Exception as exc:
                failed.append(f"{source_type.value}: healthcheck-exception: {exc}")
        if failed:
            raise AdapterCredentialsError(
                "Een of meer adapters zijn geladen maar healthcheck faalt:\n  - "
                + "\n  - ".join(failed)
                + "\nControleer Streamlit Secrets voor de juiste credentials."
            )

    def _verify_capability_consistency(self) -> None:
        """Tweede vangnet bovenop schema-validator: capability moet daadwerkelijk
        een actieve adapter hebben.

        Schema-validator pakt 'enabled in profiel' al; deze methode pakt 'enabled
        + import succesvol + healthcheck OK'.
        """
        active = set(self._adapters.keys())

        capability_to_required_source: dict[str, set[SourceType]] = {
            "current_bookkeeping":      {SourceType.MCP_EBOEKHOUDEN},
            "recent_transactions":      {SourceType.MCP_EBOEKHOUDEN, SourceType.CSV_EBOEKHOUDEN},
            "historical_pdf_analysis":  {SourceType.PDF_JAARREKENING},
            "csv_history":              {SourceType.CSV_EBOEKHOUDEN},
            "xaf_auditfile":            {SourceType.XAF},
            "multi_year_comparison":    {SourceType.CSV_EBOEKHOUDEN, SourceType.PDF_JAARREKENING, SourceType.XAF},
            "customer_debtors":         {SourceType.MCP_EBOEKHOUDEN},
            "supplier_creditors":       {SourceType.MCP_EBOEKHOUDEN},
        }
        cap_dict = self.profile.capabilities.model_dump()
        violations: list[str] = []
        for cap_name, enabled in cap_dict.items():
            if not enabled:
                continue
            required_set = capability_to_required_source.get(cap_name, set())
            if required_set and not (required_set & active):
                violations.append(
                    f"capability '{cap_name}' is true, maar geen adapter uit "
                    f"{[s.value for s in required_set]} is actief"
                )
        if violations:
            raise InconsistentProfileError(
                f"Profiel '{self.profile.profile_id}' heeft capability-violaties na laden:\n  - "
                + "\n  - ".join(violations)
            )
