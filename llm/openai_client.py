"""OpenAI client met auto-model-picker.

Probleem dat dit oplost:
- gpt-4o-mini gedeprecieerd februari 2026
- model-strings veranderen voortdurend
- gebruikers moeten niet model-strings hoeven onderhouden

Oplossing:
- OPENAI_MODEL = "auto" → code vraagt /v1/models op en pakt eerste werkende
  uit een prefererelijst (mini/snel eerst).
- OPENAI_MODEL = "<exacte-string>" → exact dat model gebruiken (geen auto).
- Resultaat wordt gecached zodat /v1/models maar één keer per sessie wordt aangeroepen.
"""
from __future__ import annotations

import logging
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 30


# Prefererelijst — chat-modellen, snel/goedkoop eerst, naam-suffix-tolerantie via "startswith".
# Volgorde = prioriteit. Eerste match in /v1/models wint.
PREFERRED_MODEL_PREFIXES: tuple[str, ...] = (
    # Snel + goedkoop (mini-varianten) — primaire keuze voor MKB-financiële vragen
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "o4-mini",
    # Mid-tier
    "gpt-5",
    "gpt-4.1",
    "gpt-4o",
    # Reasoning — alleen als niets anders bestaat
    "o3-mini",
    "o3",
)


class OpenAIError(RuntimeError):
    pass


_MODEL_CACHE: dict[str, str] = {}  # api_key_hash -> chosen_model


def _list_available_models(api_key: str) -> list[str]:
    """Roep /v1/models en geef alle model-id's terug die deze key mag aanroepen."""
    if not api_key:
        raise OpenAIError("Geen OPENAI_API_KEY beschikbaar.")
    try:
        resp = requests.get(
            f"{OPENAI_API_BASE}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OpenAIError(f"Verbinden met OpenAI faalde: {exc}") from exc
    if resp.status_code == 401:
        raise OpenAIError("OPENAI_API_KEY is ongeldig of verlopen (HTTP 401).")
    if resp.status_code != 200:
        raise OpenAIError(f"OpenAI /v1/models gaf HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    models = [m.get("id", "") for m in data.get("data", [])]
    return [m for m in models if m]


def _pick_first_match(available: Iterable[str], preferred: Iterable[str]) -> str | None:
    """Zoek eerste prefix-match. 'gpt-5-mini' matcht 'gpt-5-mini-2026-04-01' etc."""
    available_list = list(available)
    for prefix in preferred:
        # Exact match heeft voorrang op prefix-match
        for m in available_list:
            if m == prefix:
                return m
        for m in available_list:
            if m.startswith(prefix + "-") or m.startswith(prefix):
                return m
    return None


def pick_chat_model(api_key: str, configured_model: str | None = None) -> str:
    """Bepaal welk model we gebruiken.

    Args:
        api_key: OpenAI key (uit Streamlit Secrets).
        configured_model: waarde uit Secrets. "auto" of leeg → auto-pick.
            Andere waarde → die exact gebruiken.

    Returns:
        Model-string die direct in chat.completions kan.

    Raises:
        OpenAIError als geen werkend model gevonden kan worden.
    """
    cfg = (configured_model or "").strip()
    if cfg and cfg.lower() != "auto":
        return cfg  # gebruiker heeft expliciete keuze

    cache_key = api_key[:8] + api_key[-4:] if len(api_key) > 12 else "key"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    available = _list_available_models(api_key)
    if not available:
        raise OpenAIError(
            "OpenAI gaf een lege modellenlijst terug. Controleer of je key "
            "tier-toegang heeft tot chat-modellen."
        )

    chosen = _pick_first_match(available, PREFERRED_MODEL_PREFIXES)
    if not chosen:
        # Niets uit voorkeur beschikbaar — pak eerste gpt-* model dat we vinden
        gpt_models = [m for m in available if m.startswith(("gpt-", "o"))]
        if gpt_models:
            chosen = gpt_models[0]
        else:
            raise OpenAIError(
                f"Geen geschikt chat-model gevonden voor deze key. "
                f"Beschikbaar: {available[:10]}{'...' if len(available) > 10 else ''}"
            )

    logger.info("Auto-picked OpenAI model: %s (uit %d beschikbare)", chosen, len(available))
    _MODEL_CACHE[cache_key] = chosen
    return chosen


def call_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> str:
    """Eenvoudige chat-call. Returns content-string of foutmelding."""
    if not api_key:
        return "[LLM-fout: OPENAI_API_KEY ontbreekt]"
    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        return f"[LLM-netwerkfout: {exc}]"
    if resp.status_code != 200:
        return f"[LLM-HTTP {resp.status_code}: {resp.text[:300]}]"
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        return f"[LLM-parsefout: {exc}]"
