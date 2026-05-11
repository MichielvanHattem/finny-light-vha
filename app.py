"""finny-app/app.py — Streamlit UI Fase A.

Minimale UI conform ChatGPT-eindadvies 10 mei 2026:
- Geen upload-sectie (PDF/CSV/XAF zijn in deze tier niet relevant)
- Geen verborgen loaders
- Geen UI-element dat historie suggereert in YoungTech-tier
- Toon profile_id + enabled_sources + core_version + adapter_versions in beheermodus
- Fail-fast bij startup als profiel inconsistent is of credentials ontbreken
- REFUSED wordt expliciet weergegeven met missing_capability + reden
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

# Maak finny-app-root + finny_core importeerbaar
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# finny_core: probeer subdir (deploy) en zustermap (lokale dev)
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


APP_VERSION = "0.1.0a0"
LOG = logging.getLogger("finny_app")

try:
    from finny_core import __version__ as FINNY_CORE_VERSION  # type: ignore
except Exception:
    FINNY_CORE_VERSION = "unknown"


# ============================================================ Auth (minimaal)
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


# ============================================================ Tenant resolution
def resolve_tenant_id() -> str:
    """Tenant-ID komt uit secrets — niet uit URL-parameter (anti-spoofing).

    Voor Fase A: één tenant per Streamlit-deployment (Secrets bepaalt welke).
    Voor Fase D met multi-tenant: tenant uit Entra-token na SSO-login.
    """
    tenant_id = st.secrets.get("ACTIVE_TENANT_ID", "")
    if not tenant_id:
        st.error(
            "Geen ACTIVE_TENANT_ID in Streamlit Secrets. Zet deze deployment om naar "
            "één tenant via secrets — runtime-keuze is een spoofing-risico."
        )
        st.stop()
    return tenant_id


# ============================================================ Startup (fail-fast)
@st.cache_resource(show_spinner=False)
def startup(tenant_id: str) -> tuple[Profile, SourceLoader]:
    """Eén keer per Streamlit-sessie: profiel laden + adapters valideren.

    Faalt hard als profiel inconsistent is of credentials ontbreken.
    """
    profile = load_active_profile(tenant_id)
    secrets_dict: dict[str, str] = {
        "EBOEKHOUDEN_TOKEN": st.secrets.get("EBOEKHOUDEN_TOKEN", ""),
        "OPENAI_API_KEY": st.secrets.get("OPENAI_API_KEY", ""),
    }
    loader = SourceLoader(profile, secrets=secrets_dict)
    loader.validate_or_raise()
    return profile, loader


# ============================================================ Sidebar (beheermodus)
def render_sidebar(profile: Profile, loader: SourceLoader) -> None:
    with st.sidebar:
        st.header(f"Finny {APP_VERSION}")
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
            st.caption(f"• {scope.value}")


# ============================================================ Refusal-renderer
def render_refusal(
    profile: Profile,
    classified,
    missing_capability: str,
    explanation: str,
) -> None:
    """Render REFUSED netjes — geen vriendelijke PARTIAL-tekst toelaten."""
    template = profile.refusal_policy.refusal_message_template
    msg = template.format(
        profile_id=profile.profile_id,
        missing_capability=missing_capability,
        explanation=explanation,
    )
    st.error(f"**[Niet beantwoord — buiten deze configuratie]**\n\n{msg}")
    with st.expander("Waarom niet?"):
        st.markdown(
            f"- **Vraag-classificatie:** `{classified.scope.value}`\n"
            f"- **Ontbrekende capability:** `{missing_capability}`\n"
            f"- **Vereiste bronnen voor deze vraag:** "
            f"`{', '.join(s.value for s in profile.required_sources_for_scope(classified.scope))}`\n"
            f"- **Actief in deze configuratie:** "
            f"`{', '.join(s.value for s in profile.enabled_sources)}`"
        )


# ============================================================ Answering-pad
def answer_with_mcp(
    profile: Profile,
    loader: SourceLoader,
    question: str,
    classified,
) -> dict[str, Any]:
    """Hier komt later de finny_core pipeline-call. Voor Fase A skeleton-response."""
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
        return {
            "mode": "ERROR",
            "answer": f"Adapter-fout: {exc}",
            "trace": {"error": str(exc)},
        }

    payload = result.normalized_payload
    mutations = payload.get("mutations", [])
    n_mut = len(mutations)

    # Bouw context voor LLM
    sample_lines = []
    for m in mutations[:25]:
        sample_lines.append(
            f"- {m.get('date','?')}: {m.get('description','')} | "
            f"{m.get('ledgerCode','?')} | EUR {m.get('amount','?')}"
        )
    context_block = (
        f"PROFIEL: {profile.profile_id} (tier {profile.tier.value})\n"
        f"BRON: {result.quality.traceability}\n"
        f"PERIODE: {result.period[0].isoformat()} t/m {result.period[1].isoformat()}\n"
        f"AANTAL MUTATIES: {n_mut}\n"
        f"FRESHNESS: {result.quality.freshness.value}\n"
        f"VERTROUWEN: {result.quality.extraction_confidence:.2f}\n\n"
        f"EERSTE {min(n_mut,25)} MUTATIES:\n" + "\n".join(sample_lines)
    )

    system_prompt = _load_system_prompt(profile)
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    configured_model = st.secrets.get("OPENAI_MODEL", "auto")

    try:
        chosen_model = pick_chat_model(api_key, configured_model)
    except OpenAIError as exc:
        return {
            "mode": "ERROR",
            "answer": f"LLM-init faalde: {exc}",
            "trace": {"error": str(exc), "configured_model": configured_model},
        }

    answer = call_openai(
        api_key=api_key,
        model=chosen_model,
        system_prompt=system_prompt,
        user_prompt=f"VRAAG: {question}\n\nCONTEXT:\n{context_block}",
    )
    return {
        "mode": "ANSWERED",
        "answer": answer,
        "trace": {
            "source_id": result.source_id,
            "source_type": result.source_type,
            "period": [result.period[0].isoformat(), result.period[1].isoformat()],
            "retrieved_at": result.retrieved_at.isoformat(),
            "quality": {
                "freshness": result.quality.freshness.value,
                "extraction_confidence": result.quality.extraction_confidence,
                "traceability": result.quality.traceability,
            },
            "raw_reference": result.raw_reference,
            "llm_model_used": chosen_model,
            "llm_model_configured": configured_model,
        },
    }


def _load_system_prompt(profile: Profile) -> str:
    """Laad system-prompt op basis van profiel-config. Met fallback naar base.md."""
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
    return "Je bent Finny — een financiële AI-assistent. Antwoord alleen op basis van de aangereikte context."


# ============================================================ Main
def main() -> None:
    st.set_page_config(page_title=f"Finny {APP_VERSION}", layout="wide")
    if not login_gate():
        return

    tenant_id = resolve_tenant_id()
    try:
        profile, loader = startup(tenant_id)
    except TenantNotMappedError as exc:
        st.error(f"Tenant-mapping ontbreekt: {exc}")
        return
    except (InconsistentProfileError, AdapterImportError, AdapterCredentialsError) as exc:
        st.error(f"**Startup faalt — fail-fast validatie:**\n\n{exc}")
        return
    except SourceLoaderError as exc:
        st.error(f"Onverwachte loader-fout: {exc}")
        return

    render_sidebar(profile, loader)
    st.title(f"Finny — {profile.display_name}")
    st.caption(f"Stel een vraag binnen je {profile.tier.value}-configuratie.")

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

        # Capability-check vóór retrieval
        if not profile.can_answer_scope(classified.scope):
            with st.chat_message("assistant"):
                missing_cap = classified.scope.value
                explanation = (
                    f"Je vraag valt onder scope '{classified.scope.value}', "
                    f"maar dit profiel heeft daarvoor geen actieve bron-adapter."
                )
                render_refusal(profile, classified, missing_cap, explanation)
            st.session_state["messages"].append(
                {"role": "assistant", "content": f"[REFUSED — {classified.scope.value}]"}
            )
            return

        # Future jaartal → ook hard refused
        if classified.is_future(profile.historical_years_supported and 2099 or date.today().year):
            with st.chat_message("assistant"):
                st.warning("Toekomstige jaartallen kunnen niet beantwoord worden.")
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
        st.session_state["messages"].append(
            {"role": "assistant", "content": response["answer"]}
        )


if __name__ == "__main__":
    main()
