"""Pydantic-modellen voor alle 9 lagen. Single source-of-truth voor data-flow.

v7.1.0: ChatGPT-sparring-feedback verwerkt.
- SourceQuality uitgebreid met opening_balance_verified, source_type,
  structured_source, conflicting_sources_found, source_freshness.
- ConfidenceLabel gesplitst: HIGH_VERIFIED / HIGH_SINGLE_SOURCE / MEDIUM / LOW.
- AnswerMode + MissingSource ongewijzigd uit v7.0.1.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ============================================================
# RGS 3.5
# ============================================================
class RGSCategory(str, Enum):
    BALANS_ACTIVA = "balans_activa"
    BALANS_PASSIVA_EV = "balans_passiva_eigen_vermogen"
    BALANS_PASSIVA_VV = "balans_passiva_vreemd_vermogen"
    WV_OPBRENGSTEN = "wv_opbrengsten"
    WV_KOSTPRIJS = "wv_kostprijs_omzet"
    WV_BEDRIJFSLASTEN = "wv_bedrijfslasten"
    WV_FINANCIEEL = "wv_financieel_resultaat"
    WV_BELASTING = "wv_belastingen"
    MEMO = "memoriaal"


class RGSCode(BaseModel):
    code: str
    naam: str
    categorie: RGSCategory
    debet_credit: str
    niveau: int = Field(ge=1, le=5)
    parent_code: Optional[str] = None


# ============================================================
# Bron-input (Laag 1)
# ============================================================
class Bron(str, Enum):
    EBOEKHOUDEN_MCP = "eboekhouden_mcp"
    EBOEKHOUDEN_CSV = "eboekhouden_csv"
    EXACT_CSV = "exact_csv"
    EXACT_MCP = "exact_mcp"
    MONEYBIRD_CSV = "moneybird_csv"
    PDF_JAARREKENING = "pdf_jaarrekening"
    XAF_AUDITFILE = "xaf_auditfile"
    MANUAL_MAPPING = "manual_mapping"


class RawRecord(BaseModel):
    bron: Bron
    bron_id: str
    datum: date
    bedrag: Decimal
    valuta: str = "EUR"
    omschrijving: str = ""
    pakket_grootboekcode: str
    pakket_grootboeknaam: str = ""
    journaal_code: Optional[str] = None
    journaal_naam: str = ""
    factuur_ref: Optional[str] = None
    btw_percentage: Optional[Decimal] = None
    extra: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Genormaliseerd (Laag 2)
# ============================================================
class CleanRecord(BaseModel):
    raw: RawRecord
    bedrag_eur: Decimal
    is_debet: bool
    boekjaar: int
    boekperiode: int = Field(ge=1, le=12)
    validation_warnings: list[str] = Field(default_factory=list)


# ============================================================
# RGS-gemapt (Laag 3)
# ============================================================
class MappingMethod(str, Enum):
    EXACT = "exact_match"
    ONBOARDING = "onboarding_handmatig"
    UNMAPPED = "unmapped"


class MappedRecord(BaseModel):
    clean: CleanRecord
    rgs_code: Optional[RGSCode] = None
    mapping_method: MappingMethod
    mapping_audit: str = ""


# ============================================================
# Klantprofiel (D-04)
# ============================================================
class KennisNiveau(str, Enum):
    LAAG = "laag"
    MIDDEN = "midden"
    HOOG = "hoog"


class AntwoordLengte(str, Enum):
    KORT = "kort"
    NORMAAL = "normaal"
    LANG = "lang"


class ClientProfile(BaseModel):
    klant_naam: str
    branche: Optional[str] = None
    kennis_niveau: KennisNiveau = KennisNiveau.MIDDEN
    antwoord_lengte: AntwoordLengte = AntwoordLengte.NORMAAL
    foto_url: Optional[str] = None
    extra_voorkeuren: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Vraag-classificatie (Laag 5)
# ============================================================
class IntentType(str, Enum):
    BALANCE = "balance"
    RESULT = "result"
    TOTAL_COST = "total_cost"
    SPECIFIC_COST = "specific_cost"
    RATIO = "ratio"
    TREND = "trend"
    DETAILS = "details"
    FORECAST = "forecast"
    TAX_ADVICE = "tax_advice"
    OUT_OF_SCOPE = "out_of_scope"


class QueryIntent(BaseModel):
    type: IntentType
    raw_question: str
    jaren: list[int] = Field(default_factory=list)
    rgs_categorie_filter: Optional[RGSCategory] = None
    specifieke_rgs_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    klantprofiel: Optional[ClientProfile] = None


# ============================================================
# Berekening (Laag 6) - KERN
# ============================================================
class DefinitionChoice(BaseModel):
    label: str
    value: Decimal | dict | list
    bron_records_count: int
    bron_rgs_codes: list[str] = Field(default_factory=list)


# ============================================================
# D-06 - Geen-data-modus (ChatGPT Lesson 6)
# ============================================================
class AnswerMode(str, Enum):
    """Antwoord-modus volgens ChatGPT-Lesson-6 + Lesson-7."""
    ANSWERED = "answered"
    PARTIAL = "partial"
    REFUSED = "refused"


class MissingSource(BaseModel):
    bron_type: Bron
    bestand_hint: str
    reden: str
    kritiek: bool = True


# ============================================================
# D-07 v7.1.0 - Source-quality (ChatGPT Lesson 10)
# Uitgebreid n.a.v. ChatGPT-sparring 9 mei middag:
# - opening_balance_verified (kritiek voor balans-vragen)
# - source_type (transactions_csv / annual_statement_pdf / auditfile / mcp / manual)
# - structured_source (gestructureerd vs vrije tekst)
# - conflicting_sources_found (twee bronnen met verschillende cijfers)
# - source_freshness (current / stale / unknown)
# - confidence_label gesplitst: HIGH_VERIFIED / HIGH_SINGLE_SOURCE / MEDIUM / LOW
# ============================================================
class ConfidenceLabel(str, Enum):
    """ChatGPT-correctie: één label was te grof. Splitsen tussen 'sterk-verifieerbaar'
    en 'sterk-maar-eenmalig'."""
    HIGH_VERIFIED = "high_verified"          # cross_checked=True, multi-source bevestigd
    HIGH_SINGLE_SOURCE = "high_single_source"  # period+metric+amount sterk, één betrouwbare bron
    MEDIUM = "medium"                         # data aanwezig, niet cross-checked, met kanttekening
    LOW = "low"                              # data deels mist, antwoord onzeker
    NONE = "none"                            # voor REFUSED-mode


class SourceType(str, Enum):
    """Welk bron-type heeft het cijfer geleverd? Bepaalt evidence-grade-hoogte."""
    AUDITFILE_XAF = "auditfile_xaf"          # primair, gestructureerd, debet/credit gegarandeerd
    TRANSACTIONS_CSV = "transactions_csv"    # secundair, gestructureerd, mutatie-niveau
    ANNUAL_STATEMENT_PDF = "annual_statement_pdf"  # tertiair, formele rapportage, tabel-extractie
    MCP_LIVE = "mcp_live"                    # live API, vers, betrouwbaarheid afhankelijk van endpoint
    MANUAL_MAPPING = "manual_mapping"        # handmatig per onboarding
    NONE = "none"                            # voor REFUSED


class SourceFreshness(str, Enum):
    CURRENT = "current"      # data ≤7 dagen oud
    STALE = "stale"          # data >30 dagen oud
    UNKNOWN = "unknown"      # geen timestamp beschikbaar


class SourceQuality(BaseModel):
    """v7.1.0 — uitgebreid model conform ChatGPT-sparring."""
    period_match: bool          # records uit gevraagd jaar
    metric_match: bool          # compute-functie correct voor intent
    amount_found: bool          # resultaat is geen 0 én plausibel (bv. banksaldo >= 0)
    journal_codes_used: list[str] = Field(default_factory=list)
    journal_codes_excluded: list[str] = Field(default_factory=list)
    cross_checked: bool = False  # vergeleken met andere bron (bv. PDF naast CSV)
    confidence_label: ConfidenceLabel = ConfidenceLabel.MEDIUM
    quality_notes: list[str] = Field(default_factory=list)
    # NIEUW v7.1.0
    opening_balance_verified: bool = False  # KRITIEK voor balans-vragen
    source_type: SourceType = SourceType.TRANSACTIONS_CSV
    structured_source: bool = True  # gestructureerd (CSV/XAF/MCP) vs vrije-tekst (PDF)
    conflicting_sources_found: bool = False  # twee bronnen geven verschillende cijfers
    source_freshness: SourceFreshness = SourceFreshness.UNKNOWN


class CalculationResult(BaseModel):
    """Resultaat uit Laag 6. Cijfers zijn vast — LLM mag niet herrekenen."""
    intent: IntentType
    default_definition: DefinitionChoice
    alternative_definitions: list[DefinitionChoice] = Field(default_factory=list)
    eenheid: str = "EUR"
    cross_check_passed: bool = True
    cross_check_notes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    # D-06
    mode: AnswerMode = AnswerMode.ANSWERED
    missing_sources: list[MissingSource] = Field(default_factory=list)
    # D-07
    source_quality: Optional[SourceQuality] = None


# ============================================================
# LLM-uitleg + Validatie (Laag 7+8)
# ============================================================
class ExplainedAnswer(BaseModel):
    text: str
    bron_calculation: CalculationResult
    bron_records_used: list[str] = Field(default_factory=list)
    klantprofiel_toegepast: Optional[ClientProfile] = None


class ValidationStatus(str, Enum):
    OK = "ok"
    NUMBERS_MUTATED = "numbers_mutated"
    NO_SOURCE_CITED = "no_source_cited"
    OK_WITH_WARNINGS = "ok_with_warnings"
    REFUSED_AMOUNT_LEAK = "refused_amount_leak"  # NIEUW v7.1.0: REFUSED-tekst bevat bedrag


class ValidatedAnswer(BaseModel):
    explained: ExplainedAnswer
    status: ValidationStatus
    warnings: list[str] = Field(default_factory=list)
    corrections_applied: list[str] = Field(default_factory=list)


# ============================================================
# Eindoutput (Laag 9)
# ============================================================
class FinnyAnswer(BaseModel):
    text: str
    cijfers: dict[str, Any]
    bronnen: list[str]
    audit_trail: list[str]
    confidence: float
    # D-06 / D-07
    mode: AnswerMode = AnswerMode.ANSWERED
    missing_sources: list[str] = Field(default_factory=list)
    source_quality_label: Optional[ConfidenceLabel] = None


# ============================================================
# Onboarding (D-03)
# ============================================================
class OnboardingError(BaseModel):
    pakket_grootboekcode: str
    pakket_grootboeknaam: str
    transactie_voorbeelden: list[str]
    aantal_transacties: int
    suggested_rgs_code: Optional[str] = None
    suggested_rgs_naam: Optional[str] = None


# ============================================================
# D-08 v7.1.1 - Vraagcomplexiteit-taxonomie + verwachte-accuracy
# (ontwerp 9 mei middag, op verzoek DGA)
#
# Examen-analogie: niet elke vraag heeft dezelfde correctheids-target.
# Feitelijke vraag = fout betekent niet-geleerd (compute-bug).
# Relatieve vraag = fout betekent niet-goed-gelezen (context-mismatch).
# Duidingsvraag = fout betekent niet-begrepen (definitie-issue).
# Toepassingsvraag = altijd ingewikkeld (multi-bron + expliciete aannames).
#
# Volledig dialoog-systeem (ConversationContext + relatief-detector +
# clarification-prompts + LearningLog) komt in v8.0.0. Hier alleen skeleton.
# ============================================================
class QuestionComplexityTier(str, Enum):
    """Tier-taxonomie voor verwachte antwoord-accuracy."""
    L1_FACTUAL_SIMPLE = "L1_factual_simple"           # 1 bron, deterministisch, € 1 nauwkeurig — target 100%
    L2_FACTUAL_AGGREGATED = "L2_factual_aggregated"   # 1 bron, RGS-aggregaat — target 99%
    L3_FACTUAL_CROSS_BRON = "L3_factual_cross_bron"   # W&V + jaarrekening cross-check — target 99% met cross, 90% zonder
    L4_RELATIVE = "L4_relative"                        # "en vorig jaar?" — target 95% MITS context-anker
    L5_INTERPRETIVE = "L5_interpretive"                # "hoogste kosten Q1?" — target 90%, def. afhankelijk
    L6_TREND_DUIDING = "L6_trend_duiding"             # "trend 3 jaar?" — target 85%, interpretatie
    L7_DECISION_ADVIES = "L7_decision_advies"         # "kan ik X uitkeren?" — target 70-80% met expliciete onzekerheid
    L8_OUT_OF_SCOPE = "L8_out_of_scope"               # buiten Finny-bereik → REFUSED


class AnswerExpectation(BaseModel):
    """Verwachte accuracy + clarification-discipline per tier."""
    tier: QuestionComplexityTier
    target_accuracy: float = Field(ge=0.0, le=1.0)
    cross_check_recommended: bool = False
    cross_check_required: bool = False  # voor L3+ vaak verplicht
    relative_questions_before_clarify: int = 5  # drempel "Bedoel je:?"
    confidence_label_floor: Optional[ConfidenceLabel] = None  # minimaal verwacht
    notes: list[str] = Field(default_factory=list)


# Mapping bestaande IntentType -> default tier (uitbreidbaar per intent)
INTENT_TIER_MAP: dict[IntentType, QuestionComplexityTier] = {
    IntentType.RESULT: QuestionComplexityTier.L1_FACTUAL_SIMPLE,        # omzet
    IntentType.TOTAL_COST: QuestionComplexityTier.L2_FACTUAL_AGGREGATED, # totale kosten
    IntentType.SPECIFIC_COST: QuestionComplexityTier.L2_FACTUAL_AGGREGATED,
    IntentType.RATIO: QuestionComplexityTier.L3_FACTUAL_CROSS_BRON,    # brutomarge
    IntentType.BALANCE: QuestionComplexityTier.L3_FACTUAL_CROSS_BRON,  # EV, liquide
    IntentType.TREND: QuestionComplexityTier.L6_TREND_DUIDING,
    IntentType.DETAILS: QuestionComplexityTier.L5_INTERPRETIVE,
    IntentType.FORECAST: QuestionComplexityTier.L7_DECISION_ADVIES,
    IntentType.TAX_ADVICE: QuestionComplexityTier.L7_DECISION_ADVIES,
    IntentType.OUT_OF_SCOPE: QuestionComplexityTier.L8_OUT_OF_SCOPE,
}


# Default expectations per tier — overschrijfbaar per klant of intent
DEFAULT_TIER_EXPECTATIONS: dict[QuestionComplexityTier, AnswerExpectation] = {
    QuestionComplexityTier.L1_FACTUAL_SIMPLE: AnswerExpectation(
        tier=QuestionComplexityTier.L1_FACTUAL_SIMPLE,
        target_accuracy=1.00, cross_check_recommended=True, cross_check_required=False,
        relative_questions_before_clarify=5,
        confidence_label_floor=ConfidenceLabel.HIGH_SINGLE_SOURCE,
        notes=["Eén bron, deterministisch. Bij admin klopt: € 1 nauwkeurig haalbaar."],
    ),
    QuestionComplexityTier.L2_FACTUAL_AGGREGATED: AnswerExpectation(
        tier=QuestionComplexityTier.L2_FACTUAL_AGGREGATED,
        target_accuracy=0.99, cross_check_recommended=True,
        relative_questions_before_clarify=5,
        confidence_label_floor=ConfidenceLabel.HIGH_SINGLE_SOURCE,
        notes=["Aggregaat over RGS-categorie. Filter-discipline kritiek."],
    ),
    QuestionComplexityTier.L3_FACTUAL_CROSS_BRON: AnswerExpectation(
        tier=QuestionComplexityTier.L3_FACTUAL_CROSS_BRON,
        target_accuracy=0.99, cross_check_required=True,
        relative_questions_before_clarify=5,
        confidence_label_floor=ConfidenceLabel.HIGH_VERIFIED,
        notes=["Cross-check W&V + jaarrekening verplicht voor HIGH-claim."],
    ),
    QuestionComplexityTier.L4_RELATIVE: AnswerExpectation(
        tier=QuestionComplexityTier.L4_RELATIVE,
        target_accuracy=0.95, cross_check_recommended=False,
        relative_questions_before_clarify=5,
        confidence_label_floor=ConfidenceLabel.MEDIUM,
        notes=["Vereist context-anker (vorige vraag). Bij N>5: forceer 'Bedoel je:?'."],
    ),
    QuestionComplexityTier.L5_INTERPRETIVE: AnswerExpectation(
        tier=QuestionComplexityTier.L5_INTERPRETIVE,
        target_accuracy=0.90, cross_check_recommended=True,
        relative_questions_before_clarify=2,
        confidence_label_floor=ConfidenceLabel.MEDIUM,
        notes=["Definitie van 'hoogste/laagste/grootste' afhankelijk van context. Toon alternatieven."],
    ),
    QuestionComplexityTier.L6_TREND_DUIDING: AnswerExpectation(
        tier=QuestionComplexityTier.L6_TREND_DUIDING,
        target_accuracy=0.85, cross_check_recommended=True,
        relative_questions_before_clarify=1,
        confidence_label_floor=ConfidenceLabel.MEDIUM,
        notes=["Meerdere periodes + interpretatie groei/krimp. Snel naar verduidelijking."],
    ),
    QuestionComplexityTier.L7_DECISION_ADVIES: AnswerExpectation(
        tier=QuestionComplexityTier.L7_DECISION_ADVIES,
        target_accuracy=0.75, cross_check_required=True,
        relative_questions_before_clarify=0,  # ALTIJD verduidelijken
        confidence_label_floor=ConfidenceLabel.MEDIUM,
        notes=[
            "Beslisadvies vereist multi-bron + fiscale regels + expliciete aannames.",
            "Altijd verduidelijking-prompt vóór antwoord. Geen impliciete advies-oordelen.",
        ],
    ),
    QuestionComplexityTier.L8_OUT_OF_SCOPE: AnswerExpectation(
        tier=QuestionComplexityTier.L8_OUT_OF_SCOPE,
        target_accuracy=1.00,  # 100% correcte weigering
        relative_questions_before_clarify=0,
        confidence_label_floor=ConfidenceLabel.NONE,
        notes=["REFUSED met heldere reden. 100% target = consequent weigeren."],
    ),
}
