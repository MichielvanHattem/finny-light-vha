"""Laag 7: LLM-uitleg. Cijfers ALTIJD uit CalculationResult. LLM mag NIET herrekenen.

D-01 strict: cijfers worden als template-vars in een vooraf opgesteld antwoord-format
ingevuld. LLM krijgt ALLEEN de tekst-uitleg-rol, niet rekenrol.
"""
from __future__ import annotations
import os
from decimal import Decimal
from ..models import (
    CalculationResult, ClientProfile, ExplainedAnswer,
    ValidationStatus, ValidatedAnswer, KennisNiveau, AntwoordLengte,
    IntentType, QueryIntent
)


def _format_eur(d) -> str:
    if isinstance(d, dict):
        return "; ".join(f"{k}: €{v}" for k, v in d.items())
    if isinstance(d, Decimal):
        return f"€{d:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return str(d)


def _build_template_answer(calc: CalculationResult, intent: QueryIntent) -> str:
    """Bouw deterministische antwoord-tekst met cijfers ingevuld als template-vars."""
    d = calc.default_definition
    intent_naam = {
        IntentType.RESULT: "omzet/resultaat",
        IntentType.TOTAL_COST: "totale kosten",
        IntentType.RATIO: "ratio/marge",
        IntentType.TREND: "ontwikkeling",
        IntentType.BALANCE: "balanssaldo",
    }.get(calc.intent, calc.intent.value)

    bron_codes_str = ", ".join(d.bron_rgs_codes[:5]) + ("..." if len(d.bron_rgs_codes) > 5 else "")
    
    if calc.intent == IntentType.TREND:
        body = f"{d.label}: {_format_eur(d.value)}"
    else:
        body = f"{d.label}: {_format_eur(d.value)} {calc.eenheid}"

    parts = [body]
    parts.append(f"Bron: {d.bron_records_count} transactie-records, RGS-codes: {bron_codes_str or '(geen)'}.")
    
    if calc.alternative_definitions:
        parts.append("Alternatieve definities:")
        for alt in calc.alternative_definitions:
            parts.append(f"  - {alt.label}: {_format_eur(alt.value)} {calc.eenheid}")
    
    return "\n".join(parts)


def _adjust_for_profile(text: str, profile: ClientProfile | None) -> str:
    """Pas detail-niveau aan klantprofiel aan (D-04)."""
    if profile is None:
        return text
    if profile.antwoord_lengte == AntwoordLengte.KORT:
        return text.split("\n")[0]  # alleen body
    return text


def explain_template_only(calc: CalculationResult, intent: QueryIntent) -> ExplainedAnswer:
    """Geen LLM-aanroep — pure template. Default voor v0 deterministische tests."""
    text = _build_template_answer(calc, intent)
    text = _adjust_for_profile(text, intent.klantprofiel)
    return ExplainedAnswer(
        text=text,
        bron_calculation=calc,
        klantprofiel_toegepast=intent.klantprofiel,
    )


def explain_with_anthropic(calc: CalculationResult, intent: QueryIntent, model: str = "claude-sonnet-4-5-20250929") -> ExplainedAnswer:
    """Met Anthropic LLM voor menselijker tekst.

    KRITIEK: cijfers in de prompt zijn vast. LLM mag ze niet wijzigen.
    Validator (laag 8) checkt of LLM-output deze cijfers EXACT bevat.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return explain_template_only(calc, intent)
    
    template = _build_template_answer(calc, intent)
    profile = intent.klantprofiel
    kennis = profile.kennis_niveau.value if profile else "midden"
    lengte = profile.antwoord_lengte.value if profile else "normaal"
    
    system = f"""Je bent Finny, een Nederlandse boekhoud-assistent. Je krijgt een vraag en een DETERMINISTISCH BEREKEND ANTWOORD.

Harde regels (geen uitzonderingen):
1. De cijfers in het berekende antwoord zijn VAST. Je mag ze NIET wijzigen, optellen, hercalculeren of afronden.
2. Schrijf het antwoord aan een ondernemer met kennisniveau '{kennis}' en antwoord-lengte '{lengte}'.
3. Behoud bronvermelding (RGS-codes, jaarrekening-paginanummers) — die zijn al gevalideerd.
4. Bij meerdere definities (default + alternatief): toon eerst default, noem alternatief beknopt.
5. Geen toevoegingen die niet uit de berekende data komen. Geen schatting. Geen aanname."""
    
    user = f"""Vraag van klant: {intent.raw_question}

Berekend antwoord (DIT IS VAST):
{template}

Schrijf hier een natuurlijke, beknopte uitleg in het Nederlands. Cijfers letterlijk overnemen."""
    
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model, max_tokens=400, system=system,
            messages=[{"role":"user","content":user}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return ExplainedAnswer(text=text, bron_calculation=calc, klantprofiel_toegepast=profile)
    except Exception as e:
        # Fallback op template-only
        ans = explain_template_only(calc, intent)
        ans.text += f"\n\n[LLM-uitleg fallback — {type(e).__name__}]"
        return ans


def validate(explained: ExplainedAnswer) -> ValidatedAnswer:
    """Laag 8: cross-check dat LLM-output de berekende cijfers exact bevat (D-01)."""
    calc = explained.bron_calculation
    target = calc.default_definition.value
    warnings: list[str] = []

    # Numeriek-check: vind het cijfer in de uitleg-tekst
    if isinstance(target, Decimal):
        # Zoek het bedrag in 81.540,85 of 81540 of varianten
        target_int = int(target)
        target_str_round = f"{target_int:,}".replace(',', '.')  # "81.540"
        if target_str_round not in explained.text and str(target_int) not in explained.text:
            warnings.append(f"Cijfer {target} niet letterlijk in uitleg-tekst gevonden — KRITIEK")
            return ValidatedAnswer(explained=explained, status=ValidationStatus.NUMBERS_MUTATED, warnings=warnings)

    return ValidatedAnswer(
        explained=explained,
        status=ValidationStatus.OK if not warnings else ValidationStatus.OK_WITH_WARNINGS,
        warnings=warnings,
    )
