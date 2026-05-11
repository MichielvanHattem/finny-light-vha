"""Question router — classificeert vraag, QuestionScope.

ChatGPT-correctie 10 mei 2026:
- "Te vriendelijke PARTIAL waar REFUSED nodig is" is een serieus risico.
- Classifier voor retrieval: question_requires_source_type, REFUSED if unavailable.

Dit is een eenvoudige lexicale classifier voor Fase A. Latere versies kunnen LLM-gestut worden.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from profiles.schema import Profile, QuestionScope, SourceType


@dataclass(frozen=True)
class ClassifiedQuestion:
    scope: QuestionScope
    detected_year: int | None
    matched_keywords: list[str]
    raw_question: str

    def is_historical(self, current_year: int) -> bool:
        return self.detected_year is not None and self.detected_year < current_year

    def is_future(self, current_year: int) -> bool:
        return self.detected_year is not None and self.detected_year > current_year


# Keyword-mappings, bewust simpel voor Fase A.
_HIST_TRIGGERS = (
    "jaarrekening", "afgesloten boekjaar", "winst over 20", "omzet 20",
    "vorig jaar", "vorige jaren", "voorgaande jaren",
    "trend", "ontwikkeling over", "vergelijking jaren",
)
_AUDIT_TRIGGERS = ("xaf", "auditfile", "audit-file", "audit file", "saf-t")
_DEBTOR_TRIGGERS = ("debiteur", "debiteuren", "openstaand", "vordering", "klantfacturen")
_CREDITOR_TRIGGERS = ("crediteur", "crediteuren", "leveranciers", "openstaande facturen")
_BALANCE_HIST_TRIGGERS = (
    "eindbalans",
    "openingsbalans",
    "balanspositie einde",
    "balans einde",
    "balans per",
    "activa per",
    "passiva per",
    "eigen vermogen einde",
)


class QuestionScopeClassifier:
    """Eenvoudige lexicale classifier voor Fase A.

    Voor Fase B/C kan dit een LLM-gestute classifier worden. Voor MCP-only is dit
    voldoende: we hoeven alleen te detecteren of een vraag historische bronnen vereist
    zodat we hard kunnen REFUSEN.
    """

    def __init__(self, current_year: int | None = None) -> None:
        self.current_year = current_year or date.today().year

    def classify(self, question: str) -> ClassifiedQuestion:
        q = question.lower()
        keywords: list[str] = []

        year = self._detect_year(q)

        # Auditfile heeft hoogste specifiteit
        if any(t in q for t in _AUDIT_TRIGGERS):
            keywords += [t for t in _AUDIT_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.AUDIT_TRAIL, year, keywords, question)

        # Balans-historisch (voor jaartal-detectie zodat "balans einde 2024" niet door valt)
        if any(t in q for t in _BALANCE_HIST_TRIGGERS):
            keywords += [t for t in _BALANCE_HIST_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.BALANCE_HISTORICAL, year, keywords, question)

        # Multi-jaar / trend
        if "trend" in q or "vergelijk" in q or "ontwikkeling over" in q:
            keywords.append("trend_or_compare")
            return ClassifiedQuestion(QuestionScope.MULTI_YEAR_COMPARISON, year, keywords, question)

        # Jaartal in verleden, jaarrekening-territory
        if year is not None and year < self.current_year:
            keywords.append(f"jaartal_in_verleden:{year}")
            return ClassifiedQuestion(
                QuestionScope.YEAR_END_FINANCIAL_STATEMENT, year, keywords, question
            )

        # Andere historische triggers
        if any(t in q for t in _HIST_TRIGGERS):
            keywords += [t for t in _HIST_TRIGGERS if t in q]
            return ClassifiedQuestion(
                QuestionScope.YEAR_END_FINANCIAL_STATEMENT, year, keywords, question
            )

        if any(t in q for t in _DEBTOR_TRIGGERS):
            keywords += [t for t in _DEBTOR_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.CUSTOMER_DEBTORS, year, keywords, question)

        if any(t in q for t in _CREDITOR_TRIGGERS):
            keywords += [t for t in _CREDITOR_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.SUPPLIER_CREDITORS, year, keywords, question)

        # Default: lopend boekjaar
        return ClassifiedQuestion(QuestionScope.CURRENT_BOOKKEEPING, year, keywords, question)

    def _detect_year(self, q_lower: str) -> int | None:
        match = re.search(r"\b(20\d{2})\b", q_lower)
        if match:
            return int(match.group(1))
        return None


def classify_question_scope(
    question: str, profile: Profile, current_year: int | None = None
) -> ClassifiedQuestion:
    """Convenience: classify, log scope. Roeperende code besluit zelf REFUSED-pad."""
    classifier = QuestionScopeClassifier(current_year=current_year)
    return classifier.classify(question)
