"""Profielloading tests — fail-fast bij inconsistentie.

JvT-proof bewijs: profielen kunnen niet inconsistent zijn zonder dat startup faalt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Maak finny-app-root importeerbaar
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from profiles.registry import (
    list_available_profiles,
    load_profile,
    reload_all,
)
from profiles.schema import (
    Capabilities,
    Profile,
    PromptPolicy,
    QuestionScope,
    RefusalPolicy,
    SourceType,
    Tier,
)


class TestProfileSchemaConsistency:
    """Capability ↔ adapter consistency moet bij Profile-instantie hard falen."""

    def test_youngtech_loads(self):
        profile = load_profile("youngtech_mcp_only")
        assert profile.profile_id == "youngtech_mcp_only"
        assert profile.tier == Tier.YOUNGTECH
        assert SourceType.MCP_EBOEKHOUDEN in profile.enabled_sources
        assert SourceType.PDF_JAARREKENING not in profile.enabled_sources
        assert profile.capabilities.current_bookkeeping is True
        assert profile.capabilities.historical_pdf_analysis is False
        assert profile.historical_years_supported is False

    def test_demo_loads(self):
        profile = load_profile("demo_mcp_only")
        assert profile.profile_id == "demo_mcp_only"
        assert profile.tier == Tier.DEMO

    def test_all_profiles_in_registry_load(self):
        profiles = reload_all()
        available = list_available_profiles()
        for pid in available:
            assert pid in profiles, f"{pid} niet in registry na reload_all"

    def test_inconsistent_profile_raises(self):
        """Capability historical_pdf_analysis aan, maar geen PDF-adapter → moet falen."""
        with pytest.raises(ValueError, match="capability 'historical_pdf_analysis' staat aan"):
            Profile(
                profile_id="inconsistent_test",
                display_name="Inconsistent test",
                tier=Tier.DEMO,
                enabled_sources=[SourceType.MCP_EBOEKHOUDEN],
                capabilities=Capabilities(
                    current_bookkeeping=True,
                    historical_pdf_analysis=True,           # AAN, maar geen PDF-adapter actief
                ),
                historical_years_supported=True,
                prompt_policy=PromptPolicy(prompt_policy_id="x"),
            )

    def test_historical_capability_without_flag_raises(self):
        """Historische capability aan terwijl historical_years_supported=False → fail."""
        with pytest.raises(ValueError, match="historical_years_supported=False"):
            Profile(
                profile_id="bad_hist_flag",
                display_name="Bad",
                tier=Tier.DEMO,
                enabled_sources=[SourceType.PDF_JAARREKENING],
                capabilities=Capabilities(
                    historical_pdf_analysis=True,
                ),
                historical_years_supported=False,           # Inconsistent
                prompt_policy=PromptPolicy(prompt_policy_id="x"),
            )

    def test_orphan_historical_flag_raises(self):
        """historical_years_supported=True maar geen historische capability → fail."""
        with pytest.raises(ValueError, match="geen historische capability is enabled"):
            Profile(
                profile_id="orphan_flag",
                display_name="Orphan",
                tier=Tier.DEMO,
                enabled_sources=[SourceType.MCP_EBOEKHOUDEN],
                capabilities=Capabilities(
                    current_bookkeeping=True,
                ),
                historical_years_supported=True,
                prompt_policy=PromptPolicy(prompt_policy_id="x"),
            )


class TestProfileScopeMapping:
    """Scope-mapping moet auto worden afgeleid uit capabilities."""

    def test_youngtech_scopes(self):
        profile = load_profile("youngtech_mcp_only")
        # Scopes die WEL zouden moeten kunnen
        assert profile.can_answer_scope(QuestionScope.CURRENT_BOOKKEEPING)
        assert profile.can_answer_scope(QuestionScope.RECENT_TRANSACTIONS)
        assert profile.can_answer_scope(QuestionScope.CUSTOMER_DEBTORS)
        assert profile.can_answer_scope(QuestionScope.SUPPLIER_CREDITORS)
        # Scopes die NIET zouden moeten kunnen
        assert not profile.can_answer_scope(QuestionScope.YEAR_END_FINANCIAL_STATEMENT)
        assert not profile.can_answer_scope(QuestionScope.MULTI_YEAR_COMPARISON)
        assert not profile.can_answer_scope(QuestionScope.AUDIT_TRAIL)
        assert not profile.can_answer_scope(QuestionScope.BALANCE_HISTORICAL)

    def test_required_sources_for_scope(self):
        profile = load_profile("youngtech_mcp_only")
        sources = profile.required_sources_for_scope(QuestionScope.YEAR_END_FINANCIAL_STATEMENT)
        assert SourceType.PDF_JAARREKENING in sources


class TestProfileNotFound:
    def test_unknown_profile_raises(self):
        with pytest.raises(FileNotFoundError, match="niet gevonden"):
            load_profile("does_not_exist_profile_xyz")
