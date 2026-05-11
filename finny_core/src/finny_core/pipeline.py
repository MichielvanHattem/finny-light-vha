"""Pipeline-orchestrator: alle 9 lagen aaneengeregen."""
from __future__ import annotations
from pathlib import Path
from .adapters.csv_eboekhouden import ExactOnlineCSVAdapter
from .normalize.cleaner import normalize_all
from .rgs.mapper import RGSMapper, validate_administration
from .intent.classifier import classify
from .compute import engine
from .llm.explain import explain_with_anthropic, explain_template_only, validate as validate_llm
from .models import (
    QueryIntent, IntentType, ClientProfile, FinnyAnswer, OnboardingError,
    AnswerMode, MissingSource,
)


def _format_missing(ms: MissingSource) -> str:
    krit = "KRITIEK" if ms.kritiek else "wenselijk"
    return f"[{krit}] {ms.bron_type.value}: {ms.bestand_hint} — {ms.reden}"


def _refused_text(calc) -> str:
    """Bouw weiger-tekst uit CalculationResult.mode=REFUSED — geen LLM."""
    lines = [f"Ik kan deze vraag niet betrouwbaar beantwoorden uit de beschikbare administratie."]
    lines.append(f"Reden: {calc.default_definition.label}.")
    if calc.missing_sources:
        lines.append("Wat ontbreekt:")
        for ms in calc.missing_sources:
            lines.append(f"  - {_format_missing(ms)}")
    if calc.cross_check_notes:
        lines.append("Toelichting:")
        for note in calc.cross_check_notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _partial_prefix(calc) -> str:
    """Prefix voor PARTIAL-antwoorden — expliciete onzekerheid."""
    notes = "; ".join(calc.cross_check_notes) if calc.cross_check_notes else "data-onzekerheid"
    return f"[VOORWAARDELIJK ANTWOORD — {notes}]\n\n"


class FinnyPipeline:
    def __init__(self, data_dir: Path, rgs_yaml: Path, use_llm: bool = False):
        self.data_dir = Path(data_dir)
        self.rgs_yaml = Path(rgs_yaml)
        self.use_llm = use_llm
        self._mapped = None  # lazy-load
        self._onboarding_errors: list[OnboardingError] = []

    def _ensure_loaded(self):
        if self._mapped is not None:
            return
        adapter = ExactOnlineCSVAdapter()
        raws = adapter.read_directory(self.data_dir, pattern='*FinTransactionSearch*.csv')
        cleans = normalize_all(raws)
        mapper = RGSMapper(self.rgs_yaml)
        self._mapped = mapper.map_all(cleans)
        self._onboarding_errors = validate_administration(self._mapped)
        if self._onboarding_errors:
            namen = ', '.join(e.pakket_grootboeknaam for e in self._onboarding_errors[:3])
            raise RuntimeError(
                f"Onboarding-fout (D-03): {len(self._onboarding_errors)} ongekende grootboek-codes. "
                f"Eerste: {namen}. Werk RGS-mapping bij vóór gebruik."
            )

    def ask(self, question: str, profile: ClientProfile | None = None) -> FinnyAnswer:
        self._ensure_loaded()
        intent = classify(question, profile)
        audit = [f"intent={intent.type.value}", f"jaren={intent.jaren}"]

        # Compute (laag 6)
        calc = None
        if intent.type == IntentType.RESULT and intent.jaren:
            calc = engine.omzet(self._mapped, intent.jaren[0])
        elif intent.type == IntentType.TREND and intent.jaren:
            calc = engine.omzet_per_jaar(self._mapped, intent.jaren)
        elif intent.type == IntentType.TOTAL_COST and intent.jaren:
            calc = engine.totale_kosten(self._mapped, intent.jaren[0])
        elif intent.type == IntentType.RATIO and 'percentage' in question.lower():
            calc = engine.brutomarge_pct(self._mapped, intent.jaren[0])
        elif intent.type == IntentType.RATIO:
            calc = engine.brutomarge_bedrag(self._mapped, intent.jaren[0])
        elif intent.type == IntentType.BALANCE and 'liquide' in question.lower():
            calc = engine.liquide_middelen_eind(self._mapped, intent.jaren[0])
        elif intent.type == IntentType.BALANCE:
            calc = engine.eigen_vermogen_eind(self._mapped, intent.jaren[0])
        else:
            return FinnyAnswer(
                text="Niet afleidbaar uit deze administratie via finny_core v0.",
                cijfers={}, bronnen=[], audit_trail=audit + ["intent=OUT_OF_SCOPE"], confidence=0.0,
            )

        audit.append(f"compute={calc.intent.value}, default={calc.default_definition.label}, mode={calc.mode.value}")

        # D-06: REFUSED → skip LLM, geef directe weiger-tekst (ChatGPT-Lesson-6)
        if calc.mode == AnswerMode.REFUSED:
            audit.append("llm=skipped (mode=REFUSED)")
            return FinnyAnswer(
                text=_refused_text(calc),
                cijfers={},  # geen cijfers bij REFUSED
                bronnen=[],
                audit_trail=audit,
                confidence=0.0,
                mode=AnswerMode.REFUSED,
                missing_sources=[_format_missing(ms) for ms in calc.missing_sources],
                source_quality_label=calc.source_quality.confidence_label if calc.source_quality else None,
            )

        # LLM-uitleg (laag 7) + validatie (laag 8)
        if self.use_llm:
            explained = explain_with_anthropic(calc, intent)
            audit.append("llm=anthropic")
        else:
            explained = explain_template_only(calc, intent)
            audit.append("llm=template-only")
        validated = validate_llm(explained)
        audit.append(f"validation={validated.status.value}")

        # D-06: PARTIAL → prefix tekst met onzekerheid-marker
        text = validated.explained.text
        if calc.mode == AnswerMode.PARTIAL:
            text = _partial_prefix(calc) + text
            audit.append(f"mode=PARTIAL, missing={len(calc.missing_sources)} sources")

        # Output (laag 9)
        cijfers = {"default": str(calc.default_definition.value)}
        for i, alt in enumerate(calc.alternative_definitions):
            cijfers[f"alt_{i}"] = str(alt.value)
        bronnen = list(calc.default_definition.bron_rgs_codes)

        # D-07: voeg source_quality toe aan audit
        if calc.source_quality:
            audit.append(
                f"source_quality={calc.source_quality.confidence_label.value} "
                f"(jc_used={calc.source_quality.journal_codes_used}, "
                f"jc_excl={calc.source_quality.journal_codes_excluded}, "
                f"cross_checked={calc.source_quality.cross_checked})"
            )

        return FinnyAnswer(
            text=text,
            cijfers=cijfers,
            bronnen=bronnen,
            audit_trail=audit,
            confidence=calc.confidence,
            mode=calc.mode,
            missing_sources=[_format_missing(ms) for ms in calc.missing_sources],
            source_quality_label=calc.source_quality.confidence_label if calc.source_quality else None,
        )


def main():
    """CLI: python -m finny_core 'Wat was de omzet 2024?'"""
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument('question', nargs='+')
    p.add_argument('--llm', action='store_true', help='Gebruik Anthropic LLM-uitleg ipv template')
    p.add_argument('--data-dir', default='data/examples/schilderez')
    p.add_argument('--rgs-yaml', default='data/rgs_mapping_schilderez.yaml')
    args = p.parse_args()

    pipe = FinnyPipeline(Path(args.data_dir), Path(args.rgs_yaml), use_llm=args.llm)
    ans = pipe.ask(' '.join(args.question))
    print("ANTWOORD:")
    print(ans.text)
    print()
    print("CIJFERS:", json.dumps(ans.cijfers, indent=2))
    print("BRONNEN:", ans.bronnen)
    print("AUDIT:", ans.audit_trail)
