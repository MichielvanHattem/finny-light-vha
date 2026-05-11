"""Profielschema - capability contract (cluster 2 fix 11 mei 2026)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class Tier(str, Enum):
    YOUNGTECH = "youngtech"
    DEMO = "demo"
    STANDARD = "standard"
    LEGACY = "legacy"
    MAATWERK = "maatwerk"


class QuestionScope(str, Enum):
    CURRENT_BOOKKEEPING = "current_bookkeeping"
    RECENT_TRANSACTIONS = "recent_transactions"
    YEAR_END_FINANCIAL_STATEMENT = "year_end_financial_statement"
    MULTI_YEAR_COMPARISON = "multi_year_comparison"
    BALANCE_HISTORICAL = "balance_historical"
    AUDIT_TRAIL = "audit_trail"
    CUSTOMER_DEBTORS = "customer_debtors"
    SUPPLIER_CREDITORS = "supplier_creditors"
    FORECAST_REQUEST = "forecast_request"
    TAX_ADVICE_REQUEST = "tax_advice_request"
    LEGAL_ADVICE_REQUEST = "legal_advice_request"
    SCENARIO_ANALYSIS = "scenario_analysis"
    CAPABILITY_STATUS = "capability_status"
    UNRECOGNIZED_INTENT = "unrecognized_intent"


class SourceType(str, Enum):
    MCP_EBOEKHOUDEN = "mcp_eboekhouden"
    CSV_EBOEKHOUDEN = "csv_eboekhouden"
    PDF_JAARREKENING = "pdf_jaarrekening"
    XAF = "xaf"


class Capabilities(BaseModel):
    current_bookkeeping: bool = False
    recent_transactions: bool = False
    historical_pdf_analysis: bool = False
    csv_history: bool = False
    xaf_auditfile: bool = False
    multi_year_comparison: bool = False
    customer_debtors: bool = False
    supplier_creditors: bool = False
    capability_status_meta: bool = True
    scenario_with_facts: bool = False

    def to_question_scopes(self):
        scopes = set()
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
        if self.capability_status_meta:
            scopes.add(QuestionScope.CAPABILITY_STATUS)
        if self.scenario_with_facts:
            scopes.add(QuestionScope.SCENARIO_ANALYSIS)
        return scopes


class RefusalPolicy(BaseModel):
    refuse_if_required_source_missing: bool = True
    explain_missing_capability: bool = True
    suggest_upgrade_tier: bool = False
    refusal_message_template: str = (
        "Deze configuratie ({profile_id}) heeft geen ondersteuning voor "
        "{missing_capability}. {explanation}"
    )


class PromptPolicy(BaseModel):
    prompt_policy_id: str
    base_template_path: str = "prompts/base.md"
    capability_description: str = ""


class Profile(BaseModel):
    profile_id: str
    display_name: str
    tier: Tier
    schema_version: int = 1

    enabled_sources: list
    capabilities: Capabilities
    allowed_question_scopes: list = Field(default_factory=list)

    historical_years_supported: bool = False
    requires_refusal_on_missing_history: bool = True

    refusal_policy: RefusalPolicy = Field(default_factory=RefusalPolicy)
    prompt_policy: PromptPolicy

    allowed_for_tenants: list = Field(default_factory=list)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, v):
        if not v.replace("_", "").isalnum():
            raise ValueError("profile_id mag alleen letters, cijfers en underscores bevatten")
        if v != v.lower():
            raise ValueError("profile_id moet lowercase zijn")
        return v

    @field_validator("enabled_sources", mode="before")
    @classmethod
    def coerce_enabled_sources(cls, v):
        if not isinstance(v, list):
            return v
        out = []
        for item in v:
            if isinstance(item, SourceType):
                out.append(item)
            elif isinstance(item, str):
                out.append(SourceType(item))
            else:
                out.append(item)
        return out

    @field_validator("allowed_question_scopes", mode="before")
    @classmethod
    def coerce_allowed_scopes(cls, v):
        if not isinstance(v, list):
            return v
        out = []
        for item in v:
            if isinstance(item, QuestionScope):
                out.append(item)
            elif isinstance(item, str):
                out.append(QuestionScope(item))
            else:
                out.append(item)
        return out

    @model_validator(mode="after")
    def validate_consistency(self):
        if not self.allowed_question_scopes:
            self.allowed_question_scopes = sorted(self.capabilities.to_question_scopes())

        capability_to_required_source = {
            "current_bookkeeping": {SourceType.MCP_EBOEKHOUDEN},
            "recent_transactions": {SourceType.MCP_EBOEKHOUDEN, SourceType.CSV_EBOEKHOUDEN},
            "historical_pdf_analysis": {SourceType.PDF_JAARREKENING},
            "csv_history": {SourceType.CSV_EBOEKHOUDEN},
            "xaf_auditfile": {SourceType.XAF},
            "multi_year_comparison": {SourceType.CSV_EBOEKHOUDEN, SourceType.PDF_JAARREKENING, SourceType.XAF},
            "customer_debtors": {SourceType.MCP_EBOEKHOUDEN},
            "supplier_creditors": {SourceType.MCP_EBOEKHOUDEN},
            "capability_status_meta": set(),
            "scenario_with_facts": {SourceType.MCP_EBOEKHOUDEN, SourceType.CSV_EBOEKHOUDEN},
        }
        active_sources = set(self.enabled_sources)
        cap_dict = self.capabilities.model_dump()
        violations = []
        for cap_name, enabled in cap_dict.items():
            if not enabled:
                continue
            required_set = capability_to_required_source.get(cap_name, set())
            if required_set and not (required_set & active_sources):
                violations.append(
                    "capability '" + cap_name + "' staat aan, maar geen vereiste adapter is enabled."
                )
        if violations:
            raise ValueError(
                "Profiel '" + self.profile_id + "' inconsistente capability/adapter mapping:\n  - "
                + "\n  - ".join(violations)
            )

        historical_caps = (
            self.capabilities.historical_pdf_analysis
            or self.capabilities.csv_history
            or self.capabilities.xaf_auditfile
            or self.capabilities.multi_year_comparison
        )
        if historical_caps and not self.historical_years_supported:
            raise ValueError(
                "Profiel '" + self.profile_id + "': capability voor historische data staat aan, "
                "maar historical_years_supported=False."
            )
        if not historical_caps and self.historical_years_supported:
            raise ValueError(
                "Profiel '" + self.profile_id + "': historical_years_supported=True maar geen historische capability enabled."
            )
        return self

    def can_answer_scope(self, scope):
        return scope in self.allowed_question_scopes

    def required_sources_for_scope(self, scope):
        m = {
            QuestionScope.CURRENT_BOOKKEEPING: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.RECENT_TRANSACTIONS: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.YEAR_END_FINANCIAL_STATEMENT: {SourceType.PDF_JAARREKENING},
            QuestionScope.MULTI_YEAR_COMPARISON: {SourceType.CSV_EBOEKHOUDEN, SourceType.PDF_JAARREKENING},
            QuestionScope.BALANCE_HISTORICAL: {SourceType.PDF_JAARREKENING, SourceType.XAF},
            QuestionScope.AUDIT_TRAIL: {SourceType.XAF},
            QuestionScope.CUSTOMER_DEBTORS: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.SUPPLIER_CREDITORS: {SourceType.MCP_EBOEKHOUDEN},
            QuestionScope.FORECAST_REQUEST: set(),
            QuestionScope.TAX_ADVICE_REQUEST: set(),
            QuestionScope.LEGAL_ADVICE_REQUEST: set(),
            QuestionScope.UNRECOGNIZED_INTENT: set(),
            QuestionScope.CAPABILITY_STATUS: set(),
            QuestionScope.SCENARIO_ANALYSIS: {SourceType.MCP_EBOEKHOUDEN},
        }
        return m.get(scope, set())
