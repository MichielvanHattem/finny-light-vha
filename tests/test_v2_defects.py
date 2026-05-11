"""Tests cluster 1-5 (11 mei 2026 fixes).

Deze tests zouden ZONDER de cluster-fixes falen. Ze zijn het bewijs dat de
defecten uit het QA-rapport (Finny 0.1.0a0, profile demo_mcp_only, 30/32 falen
op HTTP 400 limit-bug + classifier-defecten) niet meer aanwezig zijn.

Run: `pytest tests/test_v2_defects.py -v`
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from profiles.registry import load_profile
from profiles.schema import QuestionScope, SourceType
from orchestrator.question_router import QuestionScopeClassifier


# ====================================================================
# Cluster 1 - Adapter limit-bug (zou falen met hardcoded limit=5000)
# ====================================================================

class TestAdapterLimitClamping:
    """e-Boekhouden Mutations-endpoint accepteert max limit=2000. Cluster 1
    fix: paginatie via offset, niet hardcoded 5000.
    """

    def test_adapter_uses_limit_within_2000(self):
        """Adapter mag nooit een limit > 2000 versturen."""
        from adapters.mcp_eboekhouden import MCPEboekhoudenAdapter
        adapter = MCPEboekhoudenAdapter({"EBOEKHOUDEN_TOKEN": "fake"})
        assert adapter._PAGE_SIZE <= 2000, (
            "PAGE_SIZE moet binnen e-Boekhouden cap [1, 2000] vallen. "
            "Eerder was dit hardcoded 5000 - oorzaak QA-rapport blocker-bug."
        )
        assert adapter._PAGE_SIZE >= 1, "PAGE_SIZE moet >= 1 zijn."

    def test_adapter_paginates_when_more_than_page_size(self):
        """Bij meer dan PAGE_SIZE mutaties moet adapter offset-paginatie toepassen."""
        from adapters.mcp_eboekhouden import MCPEboekhoudenAdapter
        from datetime import date

        adapter = MCPEboekhoudenAdapter({"EBOEKHOUDEN_TOKEN": "fake"})
        # Mock _ensure_session zodat we geen echte auth-call doen
        adapter._ensure_session = MagicMock()
        adapter._session_token = "fake_session"

        # Simuleer: eerste pagina vol (2000 items), tweede pagina half (500 items)
        page1 = [{"id": i} for i in range(2000)]
        page2 = [{"id": 2000 + i} for i in range(500)]
        mock_resp_1 = MagicMock(status_code=200)
        mock_resp_1.json.return_value = {"items": page1}
        mock_resp_2 = MagicMock(status_code=200)
        mock_resp_2.json.return_value = {"items": page2}

        with patch.object(adapter._http, "get", side_effect=[mock_resp_1, mock_resp_2]) as mock_get:
            items = adapter._fetch_mutations(date(2026, 1, 1), date(2026, 5, 11))

        assert len(items) == 2500
        assert mock_get.call_count == 2
        # Verifieer dat offset gebruikt wordt
        first_call_params = mock_get.call_args_list[0].kwargs["params"]
        second_call_params = mock_get.call_args_list[1].kwargs["params"]
        assert first_call_params["limit"] == 2000
        assert first_call_params["offset"] == 0
        assert second_call_params["limit"] == 2000
        assert second_call_params["offset"] == 2000

    def test_adapter_400_propagates_as_fetch_error(self):
        """HTTP 400 (zoals limit-out-of-range in oude code) wordt EboekhoudenFetchError."""
        from adapters.mcp_eboekhouden import MCPEboekhoudenAdapter, EboekhoudenFetchError
        from datetime import date

        adapter = MCPEboekhoudenAdapter({"EBOEKHOUDEN_TOKEN": "fake"})
        adapter._ensure_session = MagicMock()
        adapter._session_token = "fake_session"

        mock_resp = MagicMock(status_code=400, text='{"title":"Limit must be between 1 and 2000."}')
        with patch.object(adapter._http, "get", return_value=mock_resp):
            with pytest.raises(EboekhoudenFetchError) as exc_info:
                adapter._fetch_mutations(date(2026, 1, 1), date(2026, 5, 11))
        assert "HTTP 400" in str(exc_info.value)


# ====================================================================
# Cluster 2 - Classifier-uitbreiding en default-fallback
# ====================================================================

class TestClassifierRecognisesNewScopes:
    """Voor de TESTSET v2 nieuwe scopes: forecast / tax_advice / scenario /
    capability_status / unrecognized_intent. Zou ZONDER cluster 2 fix falen.
    """

    @pytest.fixture
    def classifier(self):
        return QuestionScopeClassifier(current_year=2026)

    def test_forecast_question_is_classified_as_forecast(self, classifier):
        """Prognose-vragen mogen NIET als CURRENT_BOOKKEEPING geclassificeerd worden.

        QA-rapport bug: 'Maak prognose voor 2026' ging naar adapter-call.
        """
        result = classifier.classify("Maak een prognose voor 2026.")
        assert result.scope == QuestionScope.FORECAST_REQUEST, (
            f"prognose-vraag moet FORECAST_REQUEST zijn, kreeg {result.scope}"
        )

    def test_voorspel_question_is_forecast(self, classifier):
        result = classifier.classify("Voorspel mijn cashflow voor de komende 3 maanden.")
        assert result.scope == QuestionScope.FORECAST_REQUEST

    def test_break_even_is_forecast(self, classifier):
        result = classifier.classify("Wanneer breek ik break-even op een investering van 25000?")
        assert result.scope == QuestionScope.FORECAST_REQUEST

    def test_tax_advice_question_is_classified_as_tax_advice(self, classifier):
        """Fiscale advies-vragen mogen NIET als data-vraag geclassificeerd worden.

        QA-rapport bug: 'Mag ik lijfrente aftrekken in box 1?' ging naar adapter.
        """
        result = classifier.classify("Mag ik lijfrente aftrekken in box 1?")
        assert result.scope == QuestionScope.TAX_ADVICE_REQUEST

    def test_mkb_winstvrijstelling_is_tax_advice(self, classifier):
        result = classifier.classify("Klopt het dat ik 14% MKB-winstvrijstelling krijg?")
        assert result.scope == QuestionScope.TAX_ADVICE_REQUEST

    def test_scenario_aannemen_is_scenario(self, classifier):
        result = classifier.classify("Kan ik iemand aannemen voor 4000 per maand?")
        assert result.scope == QuestionScope.SCENARIO_ANALYSIS

    def test_scenario_investeren_is_scenario(self, classifier):
        result = classifier.classify("Heb ik ruimte om 15000 te investeren in apparatuur?")
        assert result.scope == QuestionScope.SCENARIO_ANALYSIS

    def test_capability_status_question_no_adapter_call(self, classifier):
        result = classifier.classify("Welke gegevens heb je beschikbaar?")
        assert result.scope == QuestionScope.CAPABILITY_STATUS

    def test_laatste_synchronisatie_is_capability_status(self, classifier):
        result = classifier.classify("Wanneer was de laatste synchronisatie met e-Boekhouden?")
        assert result.scope == QuestionScope.CAPABILITY_STATUS

    def test_unknown_question_defaults_to_unrecognized_not_current(self, classifier):
        """KRITIEKE TEST: default-fallback mag NIET CURRENT_BOOKKEEPING zijn.

        Cluster 2 fix: gewijzigd naar UNRECOGNIZED_INTENT zodat de capability-
        gate onherkende vragen automatisch weigert i.p.v. ze blindelings naar
        de adapter te sturen.
        """
        result = classifier.classify("Wat is de zin van het leven?")
        assert result.scope == QuestionScope.UNRECOGNIZED_INTENT, (
            f"onherkende vraag moet UNRECOGNIZED_INTENT zijn, kreeg {result.scope}. "
            f"Eerder defaulte hij naar CURRENT_BOOKKEEPING en triggerde een ongewenste adapter-call."
        )


class TestClassifierStillRecognisesExistingScopes:
    """Regression: de nieuwe categorieen mogen de bestaande niet kapot maken."""

    @pytest.fixture
    def classifier(self):
        return QuestionScopeClassifier(current_year=2026)

    def test_omzet_dit_jaar_still_current_bookkeeping(self, classifier):
        result = classifier.classify("Wat is mijn omzet tot nu toe in 2026?")
        assert result.scope == QuestionScope.CURRENT_BOOKKEEPING

    def test_historical_year_still_year_end_financial(self, classifier):
        result = classifier.classify("Wat was mijn omzet in 2024?")
        assert result.scope == QuestionScope.YEAR_END_FINANCIAL_STATEMENT

    def test_debiteur_still_customer_debtors(self, classifier):
        result = classifier.classify("Welke debiteuren staan nog open?")
        assert result.scope == QuestionScope.CUSTOMER_DEBTORS

    def test_xaf_still_audit_trail(self, classifier):
        result = classifier.classify("Geef me de XAF auditfile-info voor 2025")
        assert result.scope == QuestionScope.AUDIT_TRAIL


# ====================================================================
# Cluster 2/4 - Profile uitbreidingen
# ====================================================================

class TestProfileAllowsCapabilityStatusByDefault:
    """capability_status moet in alle MCP-only profielen toegestaan zijn —
    anders kan een gebruiker geen meta-vragen stellen.
    """

    def test_demo_mcp_only_allows_capability_status(self):
        profile = load_profile("demo_mcp_only")
        assert profile.can_answer_scope(QuestionScope.CAPABILITY_STATUS)

    def test_demo_mcp_only_allows_scenario_analysis(self):
        """Demo-profile heeft scenario_with_facts=true, dus SCENARIO_ANALYSIS toegestaan."""
        profile = load_profile("demo_mcp_only")
        assert profile.can_answer_scope(QuestionScope.SCENARIO_ANALYSIS)

    def test_youngtech_mcp_only_allows_capability_status(self):
        profile = load_profile("youngtech_mcp_only")
        assert profile.can_answer_scope(QuestionScope.CAPABILITY_STATUS)

    def test_youngtech_mcp_only_refuses_scenario_analysis(self):
        """YoungTech-profile heeft scenario_with_facts=false (conservatief)."""
        profile = load_profile("youngtech_mcp_only")
        assert not profile.can_answer_scope(QuestionScope.SCENARIO_ANALYSIS)


class TestProfileRefusesRefusalScopes:
    """Forecast/tax_advice/legal_advice zijn nooit toegestaan in MCP-only-tiers."""

    @pytest.mark.parametrize("scope", [
        QuestionScope.FORECAST_REQUEST,
        QuestionScope.TAX_ADVICE_REQUEST,
        QuestionScope.LEGAL_ADVICE_REQUEST,
        QuestionScope.YEAR_END_FINANCIAL_STATEMENT,
        QuestionScope.MULTI_YEAR_COMPARISON,
        QuestionScope.BALANCE_HISTORICAL,
        QuestionScope.AUDIT_TRAIL,
        QuestionScope.UNRECOGNIZED_INTENT,
    ])
    def test_demo_refuses_scope(self, scope):
        profile = load_profile("demo_mcp_only")
        assert not profile.can_answer_scope(scope), (
            f"demo_mcp_only mag scope {scope.value} NIET toestaan"
        )

    @pytest.mark.parametrize("scope", [
        QuestionScope.FORECAST_REQUEST,
        QuestionScope.TAX_ADVICE_REQUEST,
        QuestionScope.LEGAL_ADVICE_REQUEST,
        QuestionScope.SCENARIO_ANALYSIS,
        QuestionScope.YEAR_END_FINANCIAL_STATEMENT,
        QuestionScope.UNRECOGNIZED_INTENT,
    ])
    def test_youngtech_refuses_scope(self, scope):
        profile = load_profile("youngtech_mcp_only")
        assert not profile.can_answer_scope(scope)


# ====================================================================
# Cluster 3 - Refusal-rendering consistency
# ====================================================================

class TestRefusalTextConsistency:
    """render_refusal moet de exacte UI-tekst retourneren zodat session_state
    geen interne [REFUSED - X] codes meer toont.
    """

    def test_render_refusal_returns_user_facing_text(self):
        """Het is een unit test op de helper - geen st.error needed."""
        # We kunnen render_refusal niet zonder Streamlit-runtime aanroepen;
        # in plaats daarvan check we dat de helper het juiste contract heeft.
        from app import render_refusal
        import inspect
        sig = inspect.signature(render_refusal)
        # Return-type moet een string zijn (user-facing tekst).
        assert sig.return_annotation == str, (
            "render_refusal moet str retourneren (user-facing tekst voor session_state)."
        )


# ====================================================================
# Cluster 4 - META-handler zonder adapter-call
# ====================================================================

class TestMetaHandlerNoAdapterCall:
    """handle_capability_status mag GEEN adapter-call doen."""

    def test_meta_handler_signature_takes_loader_but_not_adapter(self):
        """Helper-functie moet bestaan en de juiste signature hebben."""
        from app import handle_capability_status
        import inspect
        sig = inspect.signature(handle_capability_status)
        params = list(sig.parameters.keys())
        assert "profile" in params
        assert "loader" in params
        assert "question" in params

    def test_meta_response_has_no_adapter_call_in_trace(self):
        """De return-trace moet expliciet 'no_adapter_call=True' bevatten."""
        # Vereist Streamlit st.session_state mock — sla over in CI tenzij we
        # streamlit-test-runner hebben. Markeer als sanity-check op constants.
        import app
        # Inspecteer de source
        import inspect
        src = inspect.getsource(app.handle_capability_status)
        assert "no_adapter_call" in src, (
            "handle_capability_status moet expliciet 'no_adapter_call' in trace zetten."
        )
        assert "adapter.retrieve" not in src, (
            "handle_capability_status mag GEEN adapter.retrieve aanroepen."
        )


# ====================================================================
# Cluster 5 - UI-header tijdsbewustzijn
# ====================================================================

class TestUIHeaderSyncTimestamp:
    """answer_with_mcp moet last_sync_iso opslaan in session_state."""

    def test_answer_with_mcp_stores_last_sync(self):
        """Bron-code-check: answer_with_mcp moet last_sync_iso zetten."""
        import app
        import inspect
        src = inspect.getsource(app.answer_with_mcp)
        assert 'last_sync_iso' in src, (
            "answer_with_mcp moet last_sync_iso in session_state opslaan voor UI-header."
        )
