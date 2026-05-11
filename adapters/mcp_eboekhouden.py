"""MCP/REST e-Boekhouden adapter — Fase A YoungTech.

Gebruikt e-Boekhouden REST-API (Beheer → API-tokens → Bearer-token).
Levert: actuele boekhouding (lopend boekjaar), debiteuren, crediteuren.
Levert NIET: historie van vorige jaren (dat is PDF/CSV/XAF-territory).

Dependencies: alleen `requests`, `pandas`. Past bij YoungTech-tier zonder zware
PDF/CSV/XAF-libraries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests

from .base import (
    AdapterHealth,
    SourceAdapter,
    SourceFreshness,
    SourceQuery,
    SourceResult,
    UniformSourceQuality,
)

logger = logging.getLogger(__name__)

EBOEKHOUDEN_API_BASE = "https://api.e-boekhouden.nl/v1"
DEFAULT_TIMEOUT = 20


class EboekhoudenAuthError(RuntimeError):
    pass


class EboekhoudenFetchError(RuntimeError):
    pass


class MCPEboekhoudenAdapter(SourceAdapter):
    """e-Boekhouden REST-API adapter — alleen lopend boekjaar."""

    NAME = "mcp_eboekhouden"
    VERSION = "1.0.0"
    CAPABILITIES = ("current_bookkeeping", "recent_transactions", "customer_debtors", "supplier_creditors")

    def __init__(self, secrets: dict[str, str]) -> None:
        self._token = secrets.get("EBOEKHOUDEN_TOKEN", "")
        self._session_token: str | None = None
        self._session_expires_at: datetime | None = None
        self._http = requests.Session()
        self._http.headers.update({"Accept": "application/json"})

    # --------------------------------------------------------------- contract

    def healthcheck(self) -> AdapterHealth:
        if not self._token:
            return AdapterHealth(
                ok=False,
                message="EBOEKHOUDEN_TOKEN ontbreekt in Secrets — controleer Streamlit secrets.",
            )
        try:
            self._ensure_session()
            return AdapterHealth(ok=True, message="e-Boekhouden API bereikbaar.")
        except EboekhoudenAuthError as exc:
            return AdapterHealth(ok=False, message=f"Auth-fout e-Boekhouden: {exc}")
        except Exception as exc:
            return AdapterHealth(ok=False, message=f"Onverwachte healthcheck-fout: {exc}")

    def retrieve(self, query: SourceQuery) -> SourceResult:
        self._ensure_session()
        period_from = query.period_from or date(date.today().year, 1, 1)
        period_to = query.period_to or date.today()

        # Voor Fase A: één endpoint volstaat — mutations + ledgers.
        # Mutations geven W&V-data; debiteuren/crediteuren via ledger-types.
        try:
            mutations = self._fetch_mutations(period_from, period_to)
        except EboekhoudenFetchError:
            raise
        except Exception as exc:
            raise EboekhoudenFetchError(f"Mutations-fetch faalde: {exc}") from exc

        quality = UniformSourceQuality(
            source_available=True,
            source_complete=period_from <= date.today(),
            source_structured=True,
            period_coverage=(period_from, period_to),
            extraction_confidence=0.95,                  # Direct uit API, geen parser-onzekerheid
            freshness=SourceFreshness.LIVE,
            traceability=f"e-Boekhouden REST API {EBOEKHOUDEN_API_BASE}",
            cross_checked=False,
            notes=(
                f"Mutaties: {len(mutations)} rijen",
                f"Periode: {period_from} t/m {period_to}",
            ),
        )
        return SourceResult(
            source_id=f"mcp_eboekhouden:{period_from.year}",
            source_type="mcp_eboekhouden",
            period=(period_from, period_to),
            retrieved_at=datetime.now(),
            quality=quality,
            raw_reference=f"{EBOEKHOUDEN_API_BASE}/mutation",
            normalized_payload={
                "mutations": mutations,
                "intent": query.intent,
            },
        )

    # --------------------------------------------------------------- private

    def _ensure_session(self) -> None:
        """e-Boekhouden vereist exchange van bearer-token voor sessietoken (~60 min)."""
        if (
            self._session_token
            and self._session_expires_at
            and self._session_expires_at > datetime.now() + timedelta(minutes=2)
        ):
            return

        url = f"{EBOEKHOUDEN_API_BASE}/session"
        try:
            resp = self._http.post(
                url,
                json={"accessToken": self._token, "source": "FinnyApp"},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise EboekhoudenAuthError(f"Verbinden met e-Boekhouden faalde: {exc}") from exc
        if resp.status_code != 200:
            raise EboekhoudenAuthError(
                f"Auth-fout {resp.status_code} — token mogelijk verlopen of onjuist."
            )
        data = resp.json()
        self._session_token = data.get("token")
        if not self._session_token:
            raise EboekhoudenAuthError("Auth-respons bevatte geen sessietoken.")
        self._session_expires_at = datetime.now() + timedelta(minutes=55)
        self._http.headers.update({"Authorization": f"Bearer {self._session_token}"})

    def _fetch_mutations(self, from_date: date, to_date: date) -> list[dict[str, Any]]:
        url = f"{EBOEKHOUDEN_API_BASE}/mutation"
        params = {
            "dateFrom": from_date.isoformat(),
            "dateTo": to_date.isoformat(),
            "limit": 5000,
        }
        try:
            resp = self._http.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            raise EboekhoudenFetchError(f"Mutations-call faalde: {exc}") from exc
        if resp.status_code != 200:
            raise EboekhoudenFetchError(
                f"Mutations-call HTTP {resp.status_code}: {resp.text[:200]}"
            )
        body = resp.json()
        items = body.get("items") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise EboekhoudenFetchError(
                f"Onverwacht formaat — verwachtte list, kreeg {type(items).__name__}"
            )
        return items
