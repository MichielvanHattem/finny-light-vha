"""Question router - classificeert vraag naar QuestionScope.

Cluster 2 fix 11 mei 2026 (na ChatGPT TESTSET-audit):
- Nieuwe trigger-categorieen: FORECAST, TAX_ADVICE, LEGAL_ADVICE, SCENARIO,
  CAPABILITY_STATUS.
- Default-fallback gewijzigd van CURRENT_BOOKKEEPING naar UNRECOGNIZED_INTENT
  (anders gaan onherkende vragen stilzwijgend naar de adapter).
- Refusal-categorieen worden VOOR data-categorieen gecheckt om "mag ik
  aftrekken" niet als BTW-data te classificeren.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from profiles.schema import Profile, QuestionScope, SourceType


@dataclass(frozen=True)
class ClassifiedQuestion:
    scope: QuestionScope
    detected_year: int
    matched_keywords: list
    raw_question: str

    def is_historical(self, current_year: int) -> bool:
        return self.detected_year is not None and self.detected_year < current_year

    def is_future(self, current_year: int) -> bool:
        return self.detected_year is not None and self.detected_year > current_year


_HIST_TRIGGERS = (
    "jaarrekening", "afgesloten boekjaar", "winst over 20", "omzet 20",
    "vorig jaar", "vorige jaren", "voorgaande jaren",
    "trend", "ontwikkeling over", "vergelijking jaren",
)
_AUDIT_TRIGGERS = ("xaf", "auditfile", "audit-file", "audit file", "saf-t")
_DEBTOR_TRIGGERS = ("debiteur", "debiteuren", "openstaand", "vordering", "klantfacturen")
_CREDITOR_TRIGGERS = ("crediteur", "crediteuren", "leveranciers", "openstaande facturen")
_BALANCE_HIST_TRIGGERS = (
    "eindbalans", "openingsbalans", "balanspositie einde", "balans einde",
    "balans per", "activa per", "passiva per", "eigen vermogen einde",
)

_FORECAST_TRIGGERS = (
    "voorspel", "prognose", "verwacht je voor", "wat verwacht",
    "wat wordt mijn", "groei volgend", "groei ik", "groeit mijn",
    "break-even", "wat gebeurt er als", "wat als de markt", "wat als ik",
    "5-jaars", "vijfjaars", "komende 3 maanden", "komende drie maanden",
    "kwartaal q3", "q3", "q4", "halen dit jaar",
)

_TAX_ADVICE_TRIGGERS = (
    "mag ik aftrekken", "aftrekbaar", "mag ik dit aftrekken",
    "inkomstenbelasting reserveren", "reserveren voor belasting",
    "mkb-winstvrijstelling", "mkb winstvrijstelling",
    "for uitkeren", "fiscale oudedagsreserve",
    "kor", "kleine ondernemersregeling",
    "bijtelling", "lijfrente",
    "dga-salaris", "dga salaris voldoende",
    "pensioen-opbouw", "fiscaal slim",
    "belastingdienst", "wet ib",
    "fiscaal voordeel", "fiscale regeling",
)

_LEGAL_ADVICE_TRIGGERS = (
    "juridisch", "rechtsvorm", "aansprakelijkheid",
    "contract", "arbeidsvoorwaarden", "ontslag",
)

_SCENARIO_TRIGGERS = (
    "kan ik iemand aannemen", "kan ik aannemen",
    "kan ik investeren", "ruimte om te investeren", "ruimte om",
    "kan ik mijn tarief verhogen", "tarief verhogen",
    "is een investering van", "is een lease",
    "kan ik prive opnemen", "kan ik prive",
    "kan ik mezelf", "mezelf een hoger",
    "wat eerst aanpakken", "welke kosten kan ik snijden",
    "is dat verantwoord", "is mijn situatie gezond",
    "draait mijn bedrijf gezond", "financiele situatie gezond",
    "is mijn financiele", "verantwoord op basis",
)

_CAPABILITY_STATUS_TRIGGERS = (
    "welke gegevens heb je", "welke gegevens heeft finny", "wat heb je beschikbaar",
    "tot welk jaar", "welke bron gebruik je", "welke bron",
    "wanneer was de laatste", "laatste synchronisatie", "laatst gesynced",
    "welke vragen kun je niet", "welke vragen kun je",
    "welke gegevens ontbreken", "wat ontbreekt er",
    "hoe betrouwbaar", "betrouwbaarheid",
    "welke deadlines", "welke aangiftes openstaan",
    "kwaliteit van mijn boekhouding",
    "wanneer is mijn boekhouding voor het laatst",
    "welke administratie",
)

_CURRENT_BOOKKEEPING_TRIGGERS = (
    "omzet", "winst", "kosten", "marge",
    "cash", "banksaldo", "bankrekening", "geld",
    "voorraad", "personeel", "loon",
    "btw", "voorbelasting",
    "boekingen", "mutaties", "transacties",
    "eigen vermogen", "schulden", "activa", "passiva",
    "werkkapitaal", "liquiditeit", "rekening-courant", "rc",
    "prive-opname", "opname",
    "dit jaar", "dit kwartaal", "deze maand",
    "ytd", "year to date", "year-to-date",
)


class QuestionScopeClassifier:
    def __init__(self, current_year=None):
        self.current_year = current_year or date.today().year

    def classify(self, question: str) -> ClassifiedQuestion:
        q = question.lower()
        keywords = []

        year = self._detect_year(q)

        # Refusal-categorieen voor data-categorieen (anders wordt "mag ik
        # aftrekken" als BTW-data geclassificeerd).
        if any(t in q for t in _CAPABILITY_STATUS_TRIGGERS):
            keywords += [t for t in _CAPABILITY_STATUS_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.CAPABILITY_STATUS, year, keywords, question)

        if any(t in q for t in _TAX_ADVICE_TRIGGERS):
            keywords += [t for t in _TAX_ADVICE_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.TAX_ADVICE_REQUEST, year, keywords, question)

        if any(t in q for t in _LEGAL_ADVICE_TRIGGERS):
            keywords += [t for t in _LEGAL_ADVICE_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.LEGAL_ADVICE_REQUEST, year, keywords, question)

        if any(t in q for t in _FORECAST_TRIGGERS):
            keywords += [t for t in _FORECAST_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.FORECAST_REQUEST, year, keywords, question)

        if any(t in q for t in _SCENARIO_TRIGGERS):
            keywords += [t for t in _SCENARIO_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.SCENARIO_ANALYSIS, year, keywords, question)

        if any(t in q for t in _AUDIT_TRIGGERS):
            keywords += [t for t in _AUDIT_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.AUDIT_TRAIL, year, keywords, question)

        if any(t in q for t in _BALANCE_HIST_TRIGGERS):
            keywords += [t for t in _BALANCE_HIST_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.BALANCE_HISTORICAL, year, keywords, question)

        if "trend" in q or "vergelijk" in q or "ontwikkeling over" in q:
            keywords.append("trend_or_compare")
            return ClassifiedQuestion(QuestionScope.MULTI_YEAR_COMPARISON, year, keywords, question)

        if year is not None and year < self.current_year:
            keywords.append("jaartal_in_verleden:" + str(year))
            return ClassifiedQuestion(QuestionScope.YEAR_END_FINANCIAL_STATEMENT, year, keywords, question)

        if any(t in q for t in _HIST_TRIGGERS):
            keywords += [t for t in _HIST_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.YEAR_END_FINANCIAL_STATEMENT, year, keywords, question)

        if any(t in q for t in _DEBTOR_TRIGGERS):
            keywords += [t for t in _DEBTOR_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.CUSTOMER_DEBTORS, year, keywords, question)

        if any(t in q for t in _CREDITOR_TRIGGERS):
            keywords += [t for t in _CREDITOR_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.SUPPLIER_CREDITORS, year, keywords, question)

        if any(t in q for t in _CURRENT_BOOKKEEPING_TRIGGERS):
            keywords += [t for t in _CURRENT_BOOKKEEPING_TRIGGERS if t in q]
            return ClassifiedQuestion(QuestionScope.CURRENT_BOOKKEEPING, year, keywords, question)

        # Cluster 2 fix: default-fallback gewijzigd. Eerder ging een onherkende
        # vraag naar CURRENT_BOOKKEEPING - dat triggerde een adapter-call op
        # vragen die niets met administratie te maken hebben. Nu
        # UNRECOGNIZED_INTENT zodat de capability-gate hem weigert.
        return ClassifiedQuestion(QuestionScope.UNRECOGNIZED_INTENT, year, keywords, question)

    def _detect_year(self, q_lower):
        match = re.search(r"\b(20\d{2})\b", q_lower)
        if match:
            return int(match.group(1))
        return None


def classify_question_scope(question, profile, current_year=None):
    classifier = QuestionScopeClassifier(current_year=current_year)
    return classifier.classify(question)
