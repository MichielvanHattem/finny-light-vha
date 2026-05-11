"""Laag 5: vraag-classifier. Vraag (str) → QueryIntent."""
from __future__ import annotations
import re
from ..models import QueryIntent, IntentType, ClientProfile


def _extract_jaren(q: str) -> list[int]:
    return sorted(set(int(y) for y in re.findall(r'\b(20\d{2})\b', q)))


def classify(question: str, profile: ClientProfile | None = None) -> QueryIntent:
    q = question.lower()
    jaren = _extract_jaren(question) or [2024]  # default laatste

    if any(w in q for w in ['omzet', 'opbrengst', 'verkoop', 'netto-omzet']):
        if 'ontwikkeling' in q or 'over de afgelopen' in q or 'per jaar' in q or 'drie jaar' in q:
            return QueryIntent(type=IntentType.TREND, raw_question=question, jaren=[2022, 2023, 2024], klantprofiel=profile)
        return QueryIntent(type=IntentType.RESULT, raw_question=question, jaren=jaren, klantprofiel=profile)
    if 'brutomarge' in q or 'bruto marge' in q:
        return QueryIntent(type=IntentType.RATIO, raw_question=question, jaren=jaren, klantprofiel=profile)
    if 'totale kosten' in q or 'totaalkosten' in q or 'som der bedrijfslasten' in q:
        return QueryIntent(type=IntentType.TOTAL_COST, raw_question=question, jaren=jaren, klantprofiel=profile)
    if 'eigen vermogen' in q or 'kapitaal' in q:
        return QueryIntent(type=IntentType.BALANCE, raw_question=question, jaren=jaren, klantprofiel=profile)
    if 'liquide middel' in q or 'banksaldo' in q or 'kassaldo' in q:
        return QueryIntent(type=IntentType.BALANCE, raw_question=question, jaren=jaren, klantprofiel=profile)
    if 'nettowinst' in q or 'winst' in q or 'resultaat' in q:
        return QueryIntent(type=IntentType.RESULT, raw_question=question, jaren=jaren, klantprofiel=profile)
    return QueryIntent(type=IntentType.OUT_OF_SCOPE, raw_question=question, jaren=jaren, klantprofiel=profile, confidence=0.3)
