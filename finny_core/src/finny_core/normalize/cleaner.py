"""Laag 2: Normalisatie. RawRecord → CleanRecord."""
from __future__ import annotations
from decimal import Decimal
from ..models import RawRecord, CleanRecord


def normalize(raw: RawRecord) -> CleanRecord:
    """Normaliseer één RawRecord tot CleanRecord met validatie-warnings."""
    warnings: list[str] = []
    bedrag = Decimal(raw.bedrag)
    is_debet = bedrag > 0  # interne conventie: positief=debet, negatief=credit
    boekjaar = int(raw.extra.get('reporting_year', raw.datum.year))
    boekperiode = int(raw.extra.get('reporting_period', raw.datum.month))

    if not (1 <= boekperiode <= 12):
        warnings.append(f"Boekperiode {boekperiode} buiten bereik 1-12, vervangen door {raw.datum.month}")
        boekperiode = raw.datum.month

    if abs(bedrag) > Decimal('1000000'):
        warnings.append(f"Bedrag {bedrag} ongebruikelijk hoog — controleer")

    return CleanRecord(
        raw=raw, bedrag_eur=bedrag, is_debet=is_debet,
        boekjaar=boekjaar, boekperiode=boekperiode,
        validation_warnings=warnings,
    )


def normalize_all(raws):
    return [normalize(r) for r in raws]
