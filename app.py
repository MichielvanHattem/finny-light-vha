"""finny-app/app.py - Streamlit UI Fase A (cluster 1-5 fixes 11 mei 2026)."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import streamlit as st

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

for candidate in (_HERE / "finny_core" / "src", _HERE.parent / "finny_core" / "src"):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
        break

from orchestrator import (
    AdapterCredentialsError,
    AdapterImportError,
    InconsistentProfileError,
    SourceLoader,
    SourceLoaderError,
    TenantNotMappedError,
    classify_question_scope,
    load_active_profile,
)
from profiles.schema import Profile, QuestionScope, SourceType
from llm import OpenAIError, call_openai, pick_chat_model


APP_VERSION = "0.1.0a1"
LOG = logging.getLogger("finny_app")

try:
    from finny_core import __version__ as FINNY_CORE_VERSION
except Exception:
    FINNY_CORE_VERSION = "unknown"


def login_gate() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.title("Inloggen bij Finny")
    pw = st.text_input("Toegangscode", type="password", key="login_pw")
    if not st.button("Inloggen"):
        return False
    expected = st.secrets.get("FINNY_DEMO_PASSWORD", "")
    if not expected:
        st.error("FINNY_DEMO_PASSWORD niet ingesteld in Streamlit Secrets.")
        return False
    if pw != expected:
        st.error("Onjuiste toegangscode.")
        return False
    st.session_state["authenticated"] = True
    st.rerun()
    return False


def resolve_tenant_id() -> str:
    tenant_id = st.secrets.get("ACTIVE_TENANT_ID", "")
    if not tenant_id:
        st.error("Geen ACTIVE_TENANT_ID in Streamlit Secrets.")
        st.stop()
    return tenant_id


@st.cache_resource(show_spinner=False)
def startup(tenant_id: str):
    profile = load_active_profile(tenant_id)
    secrets_dict = {
        "EBOEKHOUDEN_TOKEN": st.secrets.get("EBOEKHOUDEN_TOKEN", ""),
        "OPENAI_API_KEY": st.secrets.get("OPENAI_API_KEY", ""),
    }
    loader = SourceLoader(profile, secrets=secrets_dict)
    loader.validate_or_raise()
    return profile, loader


def render_sidebar(profile, loader) -> None:
    with st.sidebar:
        st.header("Finny " + APP_VERSION)
        st.caption(profile.display_name)
        st.divider()
        st.markdown("**Configuratie**")
        st.code(
            json.dumps(
                {
                    "profile_id": profile.profile_id,
                    "tier": profile.tier.value,
                    "enabled_sources": [s.value for s in profile.enabled_sources],
                    "historical_years_supported": profile.historical_years_supported,
                    "finny_core_version": FINNY_CORE_VERSION,
                    "adapter_versions": loader.adapter_versions,
                },
                indent=2,
                default=str,
            )
        )
        st.divider()
        st.caption("Mogelijke vragen in deze tier:")
        for scope in profile.allowed_question_scopes:
            st.caption("- " + scope.value)


def render_refusal(profile, classified, missing_capability, explanation) -> str:
    template = profile.refusal_policy.refusal_message_template
    msg = template.format(
        profile_id=profile.profile_id,
        missing_capability=missing_capability,
        explanation=explanation,
    )
    user_facing_text = "**[Niet beantwoord - buiten deze configuratie]**\n\n" + msg
    st.error(user_facing_text)
    with st.expander("Waarom niet?"):
        required = ", ".join(s.value for s in profile.required_sources_for_scope(classified.scope))
        enabled = ", ".join(s.value for s in profile.enabled_sources)
        st.markdown(
            "- **Vraag-classificatie:** `" + classified.scope.value + "`\n"
            "- **Ontbrekende capability:** `" + missing_capability + "`\n"
            "- **Vereiste bronnen voor deze vraag:** `" + required + "`\n"
            "- **Actief in deze configuratie:** `" + enabled + "`"
        )
    return user_facing_text


def _user_facing_error_message(exc: Exception) -> str:
    return (
        "Ik kon je boekhouding op dit moment niet uitlezen. "
        "Dit kan een tijdelijke verbindings- of synchronisatiestoring zijn. "
        "Probeer het over een minuut opnieuw. Blijft het mislukken, "
        "controleer of je e-Boekhouden-koppeling actief is of laat het weten."
    )


def handle_capability_status(profile, loader, question):
    bronnen = ", ".join(s.value for s in profile.enabled_sources) or "geen"
    huidig_jaar = date.today().year
    cap_lijst = "\n".join("- " + s.value for s in profile.allowed_question_scopes)

    all_refusable = [
        QuestionScope.FORECAST_REQUEST,
        QuestionScope.TAX_ADVICE_REQUEST,
        QuestionScope.LEGAL_ADVICE_REQUEST,
        QuestionScope.YEAR_END_FINANCIAL_STATEMENT,
        QuestionScope.MULTI_YEAR_COMPARISON,
        QuestionScope.BALANCE_HISTORICAL,
        QuestionScope.AUDIT_TRAIL,
    ]
    niet_lines = ["- " + s.value for s in all_refusable if not profile.can_answer_scope(s)]
    niet_lijst = "\n".join(niet_lines) or "- (alle scopes ondersteund)"

    last_sync_iso = st.session_state.get("last_sync_iso")
    if last_sync_iso:
        try:
            sync_label = datetime.fromisoformat(last_sync_iso).strftime("%d-%m-%Y %H:%M")
        except Exception:
            sync_label = last_sync_iso
    else:
        sync_label = "nog niet gesynced in deze sessie"

    historisch = "ja" if profile.historical_years_supported else "nee (alleen lopend jaar)"
    answer = (
        "**Wat ik kan in deze configuratie (" + profile.display_name + ")**\n\n"
        "- Actieve bronnen: " + bronnen + "\n"
        "- Lopend boekjaar: " + str(huidig_jaar) + "\n"
        "- Historische jaren: " + historisch + "\n"
        "- Laatste synchronisatie: " + sync_label + "\n"
        "- Soorten vragen die ik kan beantwoorden:\n" + cap_lijst + "\n\n"
        "**Wat ik NIET kan in deze configuratie**\n" + niet_lijst + "\n\n"
        "Voor scenario-vragen of fiscaal/juridisch advies: neem contact op met je "
        "accountant. Voor historische jaarrekeningen: vraag om een volledige tier."
    )
    return {
        "mode": "META",
        "answer": answer,
        "trace": {
            "scope": QuestionScope.CAPABILITY_STATUS.value,
            "no_adapter_call": True,
            "profile_id": profile.profile_id,
            "tier": profile.tier.value,
            "enabled_sources": [s.value for s in profile.enabled_sources],
            "allowed_scopes": [s.value for s in profile.allowed_question_scopes],
            "adapter_versions": loader.adapter_versions,
            "last_sync_iso": last_sync_iso,
            "raw_question": question,
        },
    }


_SCENARIO_PROMPT_OVERLAY = (
    "\n\n[SCENARIO-MODUS] De gebruiker stelt een beslissings- of scenariovraag. "
    "Je MAG GEEN scenario-doorrekening, voorspelling of toekomst-aanname maken. "
    "Antwoord-patroon: (1) erken de vraag, (2) leg uit dat scenario-rekenlogica "
    "in deze configuratie niet beschikbaar is, (3) toon WEL de actuele feiten uit "
    "de administratie die relevant zijn voor deze afweging (bv. cashpositie, "
    "RC-stand, openstaande crediteuren, lopende kosten), (4) verwijs voor het "
    "scenario-gesprek naar de accountant. Geen als-dan-analyses, geen "
    "het-lijkt-me-verstandig-uitspraken."
)


def answer_with_mcp(profile, loader, question, classified):
    from adapters.base import SourceQuery

    adapter = loader.get(SourceType.MCP_EBOEKHOUDEN)
    query = SourceQuery(
        period_from=date(date.today().year, 1, 1),
        period_to=date.today(),
        intent=classified.scope.value,
        raw_question=question,
    )
    try:
        result = adapter.retrieve(query)
    except Exception as exc:
        LOG.error("Adapter retrieve failed: %s", exc, exc_info=True)
        return {
            "mode": "ERROR",
            "answer": _user_facing_error_message(exc),
            "trace": {
                "error": str(exc),
                "error_type": type(exc).__name__,
                "stage": "adapter.retrieve",
            },
        }

    st.session_state["last_sync_iso"] = result.retrieved_at.isoformat()

    payload = result.normalized_payload
    mutations = payload.get("mutations", [])
    n_mut = len(mutations)

    sample_lines = []
    for m in mutations[:25]:
        d = m.get("date", "?")
        desc = m.get("description", "")
        ledger = m.get("ledgerCode", "?")
        amount = m.get("amount", "?")
        sample_lines.append("- " + str(d) + ": " + str(desc) + " | " + str(ledger) + " | EUR " + str(amount))

    period_from = result.period[0].isoformat()
    period_to = result.period[1].isoformat()
    context_block = (
        "PROFIEL: " + profile.profile_id + " (tier " + profile.tier.value + ")\n"
        "BRON: " + result.quality.traceability + "\n"
        "PERIODE: " + period_from + " t/m " + period_to + "\n"
        "AANTAL MUTATIES: " + str(n_mut) + "\n"
        "FRESHNESS: " + result.quality.freshness.value + "\n"
        "VERTROUWEN: " + format(result.quality.extraction_confidence, ".2f") + "\n\n"
        "EERSTE " + str(min(n_mut, 25)) + " MUTATIES:\n" + "\n".join(sample_lines)
    )

    system_prompt = _load_system_prompt(profile)
    if classified.scope == QuestionScope.SCENARIO_ANALYSIS:
        system_prompt = system_prompt + _SCENARIO_PROMPT_OVERLAY

    api_key = st.secrets.get("OPENAI_API_KEY", "")
    configured_model = st.secrets.get("OPENAI_MODEL", "auto")

    try:
        chosen_model = pick_chat_model(api_key, configured_model)
    except OpenAIError as exc:
        LOG.error("LLM init failed: %s", exc, exc_info=True)
        return {
            "mode": "ERROR",
            "answer": _user_facing_error_message(exc),
            "trace": {
                "error": str(exc),
                "error_type": type(exc).__name__,
                "configured_model": configured_model,
                "stage": "llm.pick_chat_model",
            },
        }

    answer = call_openai(
        api_key=api_key,
        model=chosen_model,
        system_prompt=system_prompt,
        user_prompt="VRAAG: " + question + "\n\nCONTEXT:\n" + context_block,
    )
    return {
        "mode": "ANSWERED",
        "answer": answer,
        "trace": {
            "source_id": result.source_id,
            "source_type": result.source_type,
            "period": [period_from, period_to],
            "retrieved_at": result.retrieved_at.isoformat(),
            "quality": {
                "freshness": result.quality.freshness.value,
                "extraction_confidence": result.quality.extraction_confidence,
                "traceability": result.quality.traceability,
            },
            "raw_reference": result.raw_reference,
            "llm_model_used": chosen_model,
            "llm_model_configured": configured_model,
            "scope": classified.scope.value,
            "scenario_overlay_applied": classified.scope == QuestionScope.SCENARIO_ANALYSIS,
        },
    }


def _load_system_prompt(profile) -> str:
    candidates = [
        _HERE / profile.prompt_policy.base_template_path,
        _HERE / "prompts" / "base.md",
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                continue
    return "Je bent Finny - een financiele AI-assistent. Antwoord alleen op basis van de aangereikte context."


def main() -> None:
    st.set_page_config(page_title="Finny " + APP_VERSION, layout="wide")
    if not login_gate():
        return

    tenant_id = resolve_tenant_id()
    try:
        profile, loader = startup(tenant_id)
    except TenantNotMappedError as exc:
        st.error("Tenant-mapping ontbreekt: " + str(exc))
        return
    except (InconsistentProfileError, AdapterImportError, AdapterCredentialsError) as exc:
        st.error("**Startup faalt - fail-fast validatie:**\n\n" + str(exc))
        return
    except SourceLoaderError as exc:
        st.error("Onverwachte loader-fout: " + str(exc))
        return

    render_sidebar(profile, loader)
    st.title("Finny - " + profile.display_name)

    huidig_jaar = date.today().year
    last_sync_iso = st.session_state.get("last_sync_iso")
    if last_sync_iso:
        try:
            sync_label = datetime.fromisoformat(last_sync_iso).strftime("%d-%m-%Y %H:%M")
        except Exception:
            sync_label = last_sync_iso
    else:
        sync_label = "nog niet gesynced (eerste vraag start synchronisatie)"
    st.caption(
        "**Administratie:** " + profile.display_name + " - "
        "**Boekjaar:** " + str(huidig_jaar) + " (lopend) - "
        "**Laatst opgehaald:** " + sync_label
    )
    st.caption("Stel een vraag binnen je " + profile.tier.value + "-configuratie.")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    placeholder = "Bv. 'Wat staat er aan mutaties dit jaar?' of 'Top 5 kostenposten YTD'"
    if q := st.chat_input(placeholder):
        st.session_state["messages"].append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)

        classified = classify_question_scope(q, profile)

        if not profile.can_answer_scope(classified.scope):
            with st.chat_message("assistant"):
                missing_cap = classified.scope.value
                explanation = (
                    "Je vraag valt onder scope '" + classified.scope.value + "', "
                    "maar dit profiel heeft daarvoor geen actieve bron-adapter."
                )
                refusal_text = render_refusal(profile, classified, missing_cap, explanation)
            st.session_state["messages"].append({"role": "assistant", "content": refusal_text})
            return

        if classified.is_future(profile.historical_years_supported and 2099 or date.today().year):
            with st.chat_message("assistant"):
                st.warning("Toekomstige jaartallen kunnen niet beantwoord worden.")
            return

        if classified.scope == QuestionScope.CAPABILITY_STATUS:
            with st.chat_message("assistant"):
                meta_response = handle_capability_status(profile, loader, q)
                st.markdown(meta_response["answer"])
                with st.expander("Calculation trace"):
                    st.json(meta_response["trace"])
            st.session_state["messages"].append({"role": "assistant", "content": meta_response["answer"]})
            return

        with st.chat_message("assistant"):
            with st.spinner("e-Boekhouden bevragen..."):
                response = answer_with_mcp(profile, loader, q, classified)
            if response["mode"] == "ERROR":
                st.error(response["answer"])
            else:
                st.markdown(response["answer"])
            with st.expander("Calculation trace"):
                st.json(response["trace"])
        st.session_state["messages"].append({"role": "assistant", "content": response["answer"]})


if __name__ == "__main__":
    main()
