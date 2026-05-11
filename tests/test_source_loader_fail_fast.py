"""SourceLoader fail-fast tests.

ChatGPT-correctie #1 (zeer hoog risico): "stille degradatie bij ontbrekende adapter".
Bewijs dat de loader bij startup hard faalt — niet runtime improviseert.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.source_loader import (
    AdapterCredentialsError,
    AdapterImportError,
    InconsistentProfileError,
    SourceLoader,
)
from profiles.registry import load_profile
from profiles.schema import (
    Capabilities,
    Profile,
    PromptPolicy,
    SourceType,
    Tier,
)


class TestFailFastOnMissingCredentials:
    """Adapter geladen, maar zonder credentials, healthcheck moet falen."""

    def test_youngtech_without_token_fails_fast(self):
        profile = load_profile("youngtech_mcp_only")
        loader = SourceLoader(profile, secrets={})  # geen EBOEKHOUDEN_TOKEN
        with pytest.raises(AdapterCredentialsError, match="EBOEKHOUDEN_TOKEN ontbreekt"):
            loader.validate_or_raise()

    def test_youngtech_with_token_passes_import_check(self):
        """Met token wel: import + instantiate moet lukken (healthcheck zelf gaat dan
        proberen API te bereiken — daar willen we niet op leunen in unit-test)."""
        profile = load_profile("youngtech_mcp_only")
        loader = SourceLoader(profile, secrets={"EBOEKHOUDEN_TOKEN": "fake_token_for_unit_test"})
        # Importing zou moeten lukken — healthcheck proberen we expliciet niet
        loader._import_enabled_adapters()
        assert SourceType.MCP_EBOEKHOUDEN in loader.active_sources
        assert loader.adapter_versions["mcp_eboekhouden"] == "1.0.0"


class TestNotEnabledAdapterRaisesOnGet:
    """ChatGPT: niet-enabled adapters mogen niet stilletjes laden."""

    def test_get_unenabled_adapter_raises_keyerror(self):
        profile = load_profile("youngtech_mcp_only")
        loader = SourceLoader(profile, secrets={"EBOEKHOUDEN_TOKEN": "fake"})
        loader._import_enabled_adapters()
        with pytest.raises(KeyError, match="niet enabled in profiel"):
            loader.get(SourceType.PDF_JAARREKENING)


class TestInconsistentProfileRefuses:
    """Profile claimt capability maar geen ondersteunende adapter actief."""

    def test_orphan_capability_blocks_in_validate(self):
        """Een directly geconstrueerd profiel zou al falen in schema-validator,
        maar als iemand de schema-check zou omzeilen, moet runtime-validatie het ook pakken.
        Dit dubbele vangnet is ChatGPT-eis."""
        # Construct via dict om validator-stap te tonen
        with pytest.raises(ValueError):
            Profile(
                profile_id="orphan_runtime",
                display_name="Orphan",
                tier=Tier.DEMO,
                enabled_sources=[SourceType.MCP_EBOEKHOUDEN],
                capabilities=Capabilities(
                    current_bookkeeping=True,
                    historical_pdf_analysis=True,        # geen PDF-adapter actief
                ),
                historical_years_supported=True,
                prompt_policy=PromptPolicy(prompt_policy_id="x"),
            )


class TestUnknownSourceTypeInProfile:
    """Als ADAPTER_REGISTRY geen entry heeft voor een SourceType in profiel: fail."""

    def test_registry_covers_all_enabled_sources_for_youngtech(self):
        from orchestrator.source_loader import ADAPTER_REGISTRY

        profile = load_profile("youngtech_mcp_only")
        for source_type in profile.enabled_sources:
            assert source_type in ADAPTER_REGISTRY, (
                f"SourceType {source_type.value} in profiel maar niet in ADAPTER_REGISTRY"
            )
