"""MCP/REST e-Boekhouden adapter - Fase A YoungTech.

Gebruikt e-Boekhouden REST-API (Beheer - API-tokens - Bearer-token).
Levert: actuele boekhouding (lopend boekjaar), debiteuren, crediteuren.
Levert NIET: historie van vorige jaren (dat is PDF/CSV/XAF-territory).

Cluster 1 fix 11 mei 2026:
- limit-parameter naar 2000 (was 5000, e-Boekhouden cap = 2000)
- paginatie via offset bij meer dan 2000 mutaties
- safety-cap op 50 pagina's (100.000 mutaties) tegen runaway-loop

Dependencies: alleen `requests`, `pandas`.
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
    """e-Boekhouden REST-API adapter - alleen lopend boekjaar."""

    NAME = "mcp_eboekhouden"
    VERSION = "1.0.1"  # bump na cluster 1 limit-fix 11 mei 2026
    CAPABILITIES = ("current_bookkeeping", "recent_transactions", "customer_debtors", "supplier_creditors")

    # e-Boekhouden Mutations-endpoint accepteert limit in range [1, 2000].
    # Boven dat range geeft de API HTTP 400. Bij meer mutaties pagineren via offset.
    _PAGE_SIZE = 2000
    _MAX_PAGES_SAFETY = 50  # harde cap = 100.000 mutaties; voorkomt runaway-loop

    def __init__(self, secrets: dict) -> None:
        self._token = secrets.get("EBOEKHOUDEN_TOKEN", "")
        self._session_token = None
        self._session_expires_at = None
        self._http = requests.Session()
        self._http.headers.update({"Accept": "application/json"})

    def healthcheck(self) -> AdapterHealth:
        if not self._token:
            return AdapterHealth(
                ok=False,
                message="EBOEKHOUDEN_TOKEN ontbreekt in Secrets - controleer Streamlit secrets.",
            )
        try:
            self._ensure_session()
            return AdapterHealth(ok=True, message="e-Boekhouden API bereikbaar.")
        except EboekhoudenAuthError as exc:
            return AdapterHealth(ok=False, message="Auth-fout e-Boekhouden: " + str(exc))
        except Exception as exc:
            return AdapterHealth(ok=False, message="Onverwachte healthcheck-fout: " + str(exc))

    def retrieve(self, query: SourceQuery) -> SourceResult:
        self._ensure_session()
        period_from = query.period_from or date(date.today().year, 1, 1)
        period_to = query.period_to or date.today()

        try:
            mutations = self._fetch_mutations(period_from, period_to)
        except EboekhoudenFetchError:
            raise
        except Exception as exc:
            raise EboekhoudenFetchError("Mutations-fetch faalde: " + str(exc)) from exc

        quality = UniformSourceQuality(
            source_available=True,
            source_complete=period_from <= date.today(),
            source_structured=True,
            period_coverage=(period_from, period_to),
            extraction_confidence=0.95,
            freshness=SourceFreshness.LIVE,
            traceability="e-Boekhouden REST API " + EBOEKHOUDEN_API_BASE,
            cross_checked=False,
            notes=(
                "Mutaties: " + str(len(mutations)) + " rijen",
                "Periode: " + period_from.isoformat() + " t/m " + period_to.isoformat(),
            ),
        )
        return SourceResult(
            source_id="mcp_eboekhouden:" + str(period_from.year),
            source_type="mcp_eboekhouden",
            period=(period_from, period_to),
            retrieved_at=datetime.now(),
            quality=quality,
            raw_reference=EBOEKHOUDEN_API_BASE + "/mutation",
            normalized_payload={
                "mutations": mutations,
                "intent": query.intent,
            },
        )

    def _ensure_session(self) -> None:
        if (
            self._session_token
            and self._session_expires_at
            and self._session_expires_at > datetime.now() + timedelta(minutes=2)
        ):
            return

        url = EBOEKHOUDEN_API_BASE + "/session"
        try:
            resp = self._http.post(
                url,
                json={"accessToken": self._token, "source": "FinnyApp"},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise EboekhoudenAuthError("Verbinden met e-Boekhouden faalde: " + str(exc)) from exc
        if resp.status_code != 200:
            raise EboekhoudenAuthError(
                "Auth-fout " + str(resp.status_code) + " - token mogelijk verlopen of onjuist."
            )
        data = resp.json()
        self._session_token = data.get("token")
        if not self._session_token:
            raise EboekhoudenAuthError("Auth-respons bevatte geen sessietoken.")
        self._session_expires_at = datetime.now() + timedelta(minutes=55)
        self._http.headers.update({"Authorization": "Bearer " + self._session_token})

    def _fetch_mutations(self, from_date: date, to_date: date) -> list:
        """Haal alle mutaties op met paginatie.

        Cluster 1 fix: limit was hardcoded 5000 (out of range), nu 2000 met
        offset-paginatie. Safety-cap voorkomt oneindige loops.
        """
        url = EBOEKHOUDEN_API_BASE + "/mutation"
        all_items = []
        offset = 0

        for page_idx in range(self._MAX_PAGES_SAFETY):
            params = {
                "dateFrom": from_date.isoformat(),
                "dateTo": to_date.isoformat(),
                "limit": self._PAGE_SIZE,
                "offset": offset,
            }
            try:
                resp = self._http.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            except requests.RequestException as exc:
                raise EboekhoudenFetchError(
                    "Mutations-call faalde (pagina " + str(page_idx) + "): " + str(exc)
                ) from exc
            if resp.status_code != 200:
                raise EboekhoudenFetchError(
                    "Mutations-call HTTP " + str(resp.status_code)
                    + " op pagina " + str(page_idx) + ": " + resp.text[:200]
                )
            body = resp.json()
            items = body.get("items") if isinstance(body, dict) else body
            if not isinstance(items, list):
                raise EboekhoudenFetchError(
                    "Onverwacht formaat - verwachtte list, kreeg " + type(items).__name__
                )
            all_items.extend(items)
            if len(items) < self._PAGE_SIZE:
                break
            offset += self._PAGE_SIZE
        else:
            logger.warning(
                "Mutations-paginatie bereikte safety-cap van %s pagina's (%s mutaties).",
                self._MAX_PAGES_SAFETY,
                len(all_items),
            )
        return all_items
