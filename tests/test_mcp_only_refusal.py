"""Refusal-tests — kerneis voor JvT-review.

ChatGPT-eindadvies: "Kan het systeem aantoonbaar NIET buiten zijn profiel antwoorden?"
Antwoord moet zijn: ja, en hier is het bewijs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from profiles.registry import load_profile
from profiles.schema import QuestionScope
from orchestrator.question_router import QuestionScopeClassifier


@pytest.fixture
def youngtech_profile():
    return load_profile("youngtech_mcp_only")


@pytest.fixture
def classifier_2026():
    return QuestionScopeClassifier(current_year=2026)


class TestHistoricalQuestionsAreRefused:
    """Vragen die historische bron vereisen → REFUSED, niet PARTIAL."""

    def test_winst_jaarrekening_2024_is_refused(self, youngtech_profile, classifier_2026):
        question = "Wat was de winst over 2024 volgens de jaarrekening?"
        classified = classifier_2026.classify(question)

        # Vraag wordt geclassificeerd als historische jaarrekening-vraag
        assert classified.scope in {
            QuestionScope.YEAR_END_FINANCIAL_STATEMENT,
            QuestionScope.BALANCE_HISTORICAL,
            QuestionScope.MULTI_YEAR_COMPARISON,
        }, f"verwacht historische scope, kreeg {classified.scope}"

        # Profiel kan deze scope NIET beantwoorden
        assert not youngtech_profile.can_answer_scope(classified.scope), (
            f"YoungTech-profiel mag scope {classified.scope.value} NIET beantwoorden"
        )

        # Ontbrekende capability is duidelijk
        required = youngtech_profile.required_sources_for_scope(classified.scope)
        assert required, "scope hoort vereiste bronnen te hebben"
        assert not (set(required) & set(youngtech_profile.enabled_sources)), (
            "verwacht GEEN overlap tussen vereiste bronnen en enabled_sources"
        )

    def test_omzet_2024_is_refused(self, youngtech_profile, classifier_2026):
        question = "Wat was mijn omzet 2024?"
        classified = classifier_2026.classify(question)
        assert classified.detected_year == 2024
        assert classified.is_historical(current_year=2026)
        assert not youngtech_profile.can_answer_scope(classified.scope)

    def test_balans_einde_2024_is_refused(self, youngtech_profile, classifier_2026):
        question = "Wat was de balans einde 2024?"
        classified = classifier_2026.classify(question)
        assert classified.scope == QuestionScope.BALANCE_HISTORICAL
        assert not youngtech_profile.can_answer_scope(classified.scope)

    def test_xaf_auditfile_is_refused(self, youngtech_profile, classifier_2026):
        question = "Geef me de XAF auditfile-info voor 2025"
        classified = classifier_2026.classify(question)
        assert classified.scope == QuestionScope.AUDIT_TRAIL
        assert not youngtech_profile.can_answer_scope(classified.scope)

    def test_multi_year_trend_is_refused(self, youngtech_profile, classifier_2026):
        question = "Hoe is mijn omzet-trend ontwikkeling over de afgelopen jaren?"
        classified = classifier_2026.classify(question)
        assert classified.scope in {
            QuestionScope.MULTI_YEAR_COMPARISON,
            QuestionScope.YEAR_END_FINANCIAL_STATEMENT,
        }
        assert not youngtech_profile.can_answer_scope(classified.scope)


class TestCurrentYearQuestionsAreAccepted:
    """Vragen binnen MCP-scope (lopend boekjaar) → toegestaan."""

    def test_omzet_dit_jaar_is_accepted(self, youngtech_profile, classifier_2026):
        question = "Wat is mijn omzet dit jaar?"
        classified = classifier_2026.classify(question)
        assert youngtech_profile.can_answer_scope(classified.scope)

    def test_top5_kosten_ytd_is_accepted(self, youngtech_profile, classifier_2026):
        question = "Top 5 kostenposten YTD"
        classified = classifier_2026.classify(question)
        assert youngtech_profile.can_answer_scope(classified.scope)

    def test_debiteuren_actueel_is_accepted(self, youngtech_profile, classifier_2026):
        question = "Welke debiteuren staan nog open?"
        classified = classifier_2026.classify(question)
        assert classified.scope == QuestionScope.CUSTOMER_DEBTORS
        assert youngtech_profile.can_answer_scope(classified.scope)

    def test_crediteuren_is_accepted(self, youngtech_profile, classifier_2026):
        question = "Welke crediteuren moeten nog betaald worden?"
        classified = classifier_2026.classify(question)
        assert classified.scope == QuestionScope.SUPPLIER_CREDITORS
        assert youngtech_profile.can_answer_scope(classified.scope)


class TestNoSilentDegradation:
    """Geen 'vriendelijke PARTIAL' bij ontbrekende historische bron."""

    def test_refusal_message_template_mentions_missing(self, youngtech_profile):
        template = youngtech_profile.refusal_policy.refusal_message_template
        assert "{missing_capability}" in template, (
            "refusal_message_template moet placeholder voor missing_capability bevatten"
        )
        assert youngtech_profile.refusal_policy.refuse_if_required_source_missing is True
        assert youngtech_profile.refusal_policy.explain_missing_capability is True
