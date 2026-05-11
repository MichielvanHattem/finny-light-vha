"""Profielschema — capability contract.

ChatGPT-eindadvies 10 mei 2026:
- enabled_sources mag GEEN vrijblijvende featureflag zijn.
- Het is een capability contract met:
  - allowed_question_scopes (welke vraagtypen mag ik beantwoorden)
  - historical_years_supported (true/false)
  - requires_refusal_on_missing_history (true/false)
- Profiel wordt bij startup hard gevalideerd. Bij inconsistentie: app start niet.
- Vraag buiten capability → REFUSED met heldere uitleg, NIET PARTIAL.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Tier(str, Enum):
    """Product-tiers conform 24-april-architectuur (klantonboarding-blueprint)."""
    YOUNGTECH = "youngtech"          # B2C zelfboeker, MCP-only
    DEMO = "demo"                    # Interne demo
    STANDARD = "standard"             # B2B met historie (Exact ZIP)
    LEGACY = "legacy"                 # Bestaande VHA-klanten met file-history
    MAATWERK = "maatwerk"             # Niet-Exact pakketten


class QuestionScope(str, Enum):
    """Vraagtypen die een profiel mag beantwoorden.

    De question-classifier mapt elke binnenkomende vraag op één van deze scopes.
    Als de scope niet in `allowed_question_scopes` van het profiel staat → REFUSED.
    """
    CURRENT_BOOKKEEPING = "current_bookkeeping"          # Lopend boekjaar via MCP
    RECENT_TRANSACTIONS = "recent_transactions"           # Mutaties laatste N maanden
    YEAR_END_FINANCIAL_STATEMENT = "year_end_financial_statement"   # Jaarrekening (PDF/XAF nodig)
    MULTI_YEAR_COMPARISON = "multi_year_comparison"      # Trend over meerdere jaren (PDF/CSV/XAF)
    BALANCE_HISTORICAL = "balance_historical"             # Historische balanspositie
    AUDIT_TRAIL = "audit_trail"                           # XAF auditfile-vragen
    CUSTOMER_DEBTORS = "customer_debtors"                 # Debiteuren actueel (MCP)
    SUPPLIER_CREDITORS = "supplier_creditors"             # Crediteuren actueel (MCP)


class SourceType(str, Enum):
    """Adapter-types die kunnen worden geactiveerd."""
    MCP_EBOEKHOUDEN = "mcp_eboekhouden"
    CSV_EBOEKHOUDEN = "csv_eboekhouden"
    PDF_JAARREKENING = "pdf_jaarrekening"
    XAF = "xaf"


class Capabilities(BaseModel):
    """Wat dit profiel KAN. Dit is harde productlogica."""
    current_bookkeeping: bool = False
    recent_transactions: bool = False
    historical_pdf_analysis: bool = False
    csv_history: bool = False
    xaf_auditfile: bool = False
    multi_year_comparison: bool = False
    customer_debtors: bool = False
    supplier_creditors: bool = False

    def to_question_scopes(self) -> set[QuestionScope]:
        """Map capabilities → toegestane vraag-scopes."""
        scopes: set[QuestionScope] = set()
        if self.current_bookkeeping:
            scopes.add(QuestionScope.CURRENT_BOOKKEEPING)
        if self.recent_transactions:
            scopes.add(QuestionScope.RECENT_TRANSACTIONS)
        if self.historical_pdf_analysis:
            scopes.add(QuestionScope.YEAR_END_FINANCIAL_STATEMENT)
            scopes.add(QuestionScope.BALANCE_HISTORICAL)
        if self.multi_year_comparison:
            scopes.add(QuestionScope.MULTI_YEAR_COMPARISON)
        if self.xaf_auditfile:
            scopes.add(QuestionScope.AUDIT_TRAIL)
        if self.customer_debtors:
            scopes.add(QuestionScope.CUSTOMER_DEBTORS)
        if self.supplier_creditors:
            scopes.add(QuestionScope.SUPPLIER_CREDITORS)
        return scopes


class RefusalPolicy(BaseModel):
    """Wat moet er gebeuren als een vraag buiten capability valt.

    ChatGPT-correctie: harde refusal, GEEN vriendelijke PARTIAL bij ontbrekende bron.
    """
    refuse_if_required_source_missing: bool = True
    explain_missing_capability: bool = True
    suggest_upgrade_tier: bool = False                # Mag Finny doorverwijzen naar hogere tier?
    refusal_message_template: str = (
        "Deze configuratie ({profile_id}) heeft geen ondersteuning voor "
        "{missing_capability}. {explanation}"
    )


class PromptPolicy(BaseModel):
    """Welke prompt-template + capability-beschrijving deze configuratie gebruikt.

    ChatGPT-correctie: prompt mag NIET vermelden wat het profiel niet kan.
    Dynamisch opbouwen uit profiel-capabilities.
    """
    prompt_policy_id: str
    base_template_path: str = "prompts/base.md"
    capability_description: str = ""                  # Wordt in system prompt gerenderd


class Profile(BaseModel):
    """Capability contract — bron van waarheid voor wat dit profiel mag.

    Dit is GEEN secrets-config. Profielen leven in versiebeheer (profiles/<id>.toml).
    Secrets bevatten ALLEEN credentials per actieve adapter.
    """
    profile_id: str
    display_name: str
    tier: Tier
    schema_version: int = 1

    # Welke adapters actief zijn voor dit profiel.
    enabled_sources: list[SourceType]

    # Capability contract — dit is wat het profiel KAN beloven.
    capabilities: Capabilities

    # Welke vraag-scopes expliciet zijn toegestaan (afgeleid van capabilities).
    # Wordt automatisch gevuld als leeg.
    allowed_question_scopes: list[QuestionScope] = Field(default_factory=list)

    historical_years_supported: bool = False
    requires_refusal_on_missing_history: bool = True

    refusal_policy: RefusalPolicy = Field(default_factory=RefusalPolicy)
    prompt_policy: PromptPolicy

    # Welke profielen mag een tenant kiezen (anti-spoofing).
    # Wordt gevalideerd door profile_loader op basis van tenant-mapping in repo-config.
    allowed_for_tenants: list[str] = Field(default_factory=list)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("profile_id mag alleen letters, cijfers en underscores bevatten")
        if v != v.lower():
            raise ValueError("profile_id moet lowercase zijn")
        return v

    @model_validator(mode="after")
    def validate_consistency(self) -> "Profile":
        """Capability ↔ enabled_sources consistentie check.

        Dit is een FAIL-FAST check: als een capability iets belooft wat geen enkele
        actieve adapter kan leveren, dan crasht profielloading.
        """
        if not self.allowed_question_scopes:
            self.allowed_question_scopes = sorted(self.capabilities.to_question_scopes())

        # Capability vs adapter validatie
        capability_to_required_source: dict[str, set[SourceType]] = {
            "current_bookkeeping":      {SourceType.MCP_EBOEKHOUDEN},
            "recent_transactions":      {SourceType.MCP_EBOEKHOUDEN, SourceType.CSV_EBOEKHOUDEN},
            "historical_pdf_analysis":  {SourceType.PDF_JAARREKENING},
            "csv_history":              {SourceType.CSV_EBOEKHOUDEN},
            "xaf_auditfile":            {SourceType.XAF},
            "multi_year_comparison":    {SourceType.CSV_EBOEKHOUDEN, SourceType.PDF_JAARREKENING, SourceType.XAF},
            "customer_debtors":         {SourceType.MCP_EBOEKHOUDEN},
            "supplier_creditors":       {SourceType.MCP_EBOEKHOUDEN},
        }
        active_sources = set(self.enabled_sources)
        cap_dict = self.capabilities.model_dump()
        violations: list[str] = []
        for cap_name, enabled in cap_dict.items():
            if not enabled:
                continue
            required_set = capability_to_required_source.get(cap_name, set())
            if required_set and not (required_set & active_sources):
                violations.append(
                    f"capability '{cap_name}' staat aan, maar geen enkele vereiste adapter "
                    f"({', '.join(s.value for s in required_set)}) is enabled. "
                    f"Actieve adapters: {[s.value for s in active_sources] or 'geen'}"
                )
        if violations:
            raise ValueError(
                f"Profiel '{self.profile_id}' heeft inconsistente capability ↔ adapter mapping:\n  - "
                + "\n  - ".join(violations)
            )

        # Historische jaren consistentie
        historical_caps = (
            self.capabilities.historical_pdf_analysis
            or self.capabilities.csv_history
            or self.capabilities.xaf_auditfile
            or self.capabilities.multi_year_comparison
        )
        if historical_caps and not self.historical_years_supported:
            raise ValueError(
                f"Profiel '{self.profile_id}': een capability voor historische data staat aan, "
                f"maar historical_years_supported=False. Inconsistent."
            )
        if not historical_caps and self.historical_years_supported:
            raise ValueError(
                f"Profiel '{self.profile_id}': historical_years_supported=True maar geen "
                f"historische capability is enabled. Inconsistent."
            )
        return self

    def can_answer_scope(self, scope: QuestionScope) -> bool:
        """Mag dit profiel een vraag van deze scope beantwoorden?"""
        return scope in self.allowed_question_scopes

    def required_sources_for_scope(self, scope: QuestionScope) -> set[SourceType]:
        """Welke adapters zijn nodig voor deze scope (voor refusal-uitleg)."""
        scope_to_sources: dict[QuestionScope, set[SourceType]] = {
            QuestionScope.CURRENT_BOOKKEEPING: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.RECENT_TRANSACTIONS: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.YEAR_END_FINANCIAL_STATEMENT: {SourceType.PDF_JAARREKENING},
            QuestionScope.MULTI_YEAR_COMPARISON: {SourceType.CSV_EBOEKHOUDEN, SourceType.PDF_JAARREKENING},
            QuestionScope.BALANCE_HISTORICAL: {SourceType.PDF_JAARREKENING, SourceType.XAF},
            QuestionScope.AUDIT_TRAIL: {SourceType.XAF},
            QuestionScope.CUSTOMER_DEBTORS: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.SUPPLIER_CREDITORS: {SourceType.MCP_EBOEKHOUDEN},
        }
        return scope_to_sources.get(scope, set())
