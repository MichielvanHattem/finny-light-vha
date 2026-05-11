"""OpenAI client met auto-model-picker (cluster 6 fix 11 mei 2026)."""
from __future__ import annotations

import logging
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 30

PREFERRED_MODEL_PREFIXES = (
    "gpt-5-mini", "gpt-5-nano",
    "gpt-4.1-mini", "gpt-4.1-nano", "o4-mini",
    "gpt-5", "gpt-4.1", "gpt-4o",
    "o3-mini", "o3",
)


class OpenAIError(RuntimeError):
    pass


_MODEL_CACHE = {}


def _list_available_models(api_key):
    if not api_key:
        raise OpenAIError("Geen OPENAI_API_KEY beschikbaar.")
    try:
        resp = requests.get(
            OPENAI_API_BASE + "/models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OpenAIError("Verbinden met OpenAI faalde: " + str(exc)) from exc
    if resp.status_code == 401:
        raise OpenAIError("OPENAI_API_KEY is ongeldig of verlopen (HTTP 401).")
    if resp.status_code != 200:
        raise OpenAIError("OpenAI /v1/models gaf HTTP " + str(resp.status_code) + ": " + resp.text[:300])
    data = resp.json()
    models = [m.get("id", "") for m in data.get("data", [])]
    return [m for m in models if m]


def _pick_first_match(available, preferred):
    avail = list(available)
    for prefix in preferred:
        for m in avail:
            if m == prefix:
                return m
        for m in avail:
            if m.startswith(prefix + "-") or m.startswith(prefix):
                return m
    return None


def pick_chat_model(api_key, configured_model=None):
    cfg = (configured_model or "").strip()
    if cfg and cfg.lower() != "auto":
        return cfg
    cache_key = api_key[:8] + api_key[-4:] if len(api_key) > 12 else "key"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]
    available = _list_available_models(api_key)
    if not available:
        raise OpenAIError("OpenAI gaf lege modellenlijst. Controleer key-tier.")
    chosen = _pick_first_match(available, PREFERRED_MODEL_PREFIXES)
    if not chosen:
        gpt_models = [m for m in available if m.startswith(("gpt-", "o"))]
        if gpt_models:
            chosen = gpt_models[0]
        else:
            raise OpenAIError("Geen geschikt chat-model gevonden voor deze key.")
    logger.info("Auto-picked model: %s", chosen)
    _MODEL_CACHE[cache_key] = chosen
    return chosen


_MODELS_NO_TEMPERATURE = ("gpt-5", "o1", "o3", "o4")


def _model_supports_temperature(model):
    if not model:
        return True
    for prefix in _MODELS_NO_TEMPERATURE:
        if model.startswith(prefix):
            return False
    return True


def call_openai(api_key, model, system_prompt, user_prompt, temperature=0.2):
    if not api_key:
        return "Ik kan op dit moment geen verbinding maken met de AI-laag (configuratie ontbreekt). Probeer het later opnieuw."
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if _model_supports_temperature(model):
        body["temperature"] = temperature

    def _post(payload):
        return requests.post(
            OPENAI_API_BASE + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )

    try:
        resp = _post(body)
    except requests.RequestException as exc:
        logger.error("OpenAI netwerk: %s", exc)
        return "Ik kan op dit moment de AI-laag niet bereiken. Probeer het over een minuut opnieuw."

    if resp.status_code == 400 and "temperature" in resp.text:
        body.pop("temperature", None)
        try:
            resp = _post(body)
        except requests.RequestException as exc:
            return "Ik kan op dit moment de AI-laag niet bereiken. Probeer het over een minuut opnieuw."

    if resp.status_code != 200:
        logger.error("OpenAI HTTP %s: %s", resp.status_code, resp.text[:300])
        return (
            "Ik kon je vraag niet door de AI-laag laten beantwoorden. Er trad een "
            "technische fout op (status " + str(resp.status_code) + "). Probeer opnieuw of laat het weten."
        )

    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return "Ik kreeg een onverwacht antwoord van de AI-laag. Probeer je vraag opnieuw te stellen."
