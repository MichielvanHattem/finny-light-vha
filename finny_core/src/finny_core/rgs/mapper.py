"""Laag 3: RGS 3.5 mapping. CleanRecord → MappedRecord.

D-03 KEUZE (Michiel akkoord 8 mei): 100% mapping verplicht.
- Bekende pakket_grootboeknaam → exact RGS-mapping
- Onbekende naam → MappingMethod.UNMAPPED + OnboardingError
- Pipeline weigert te draaien als er onbekende records zijn (onboarding-blokker).
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Any
import yaml

from ..models import (
    CleanRecord, MappedRecord, RGSCode, RGSCategory,
    MappingMethod, OnboardingError,
)


class RGSMapper:
    def __init__(self, mapping_yaml_path: Path):
        with open(mapping_yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        raw_mappings = data.get('mappings', {})
        self._mappings: dict[str, RGSCode] = {}
        for naam, m in raw_mappings.items():
            self._mappings[naam] = RGSCode(
                code=m['rgs_code'],
                naam=m['rgs_naam'],
                categorie=RGSCategory(m['categorie']),
                debet_credit=m['natuurlijke_kant'],
                niveau=4,  # default niveau, kan later per regel
            )

    def map_one(self, clean: CleanRecord) -> MappedRecord:
        naam = clean.raw.pakket_grootboeknaam
        rgs = self._mappings.get(naam)
        if rgs is not None:
            return MappedRecord(
                clean=clean, rgs_code=rgs,
                mapping_method=MappingMethod.EXACT,
                mapping_audit=f"name='{naam}' -> RGS:{rgs.code}",
            )
        return MappedRecord(
            clean=clean, rgs_code=None,
            mapping_method=MappingMethod.UNMAPPED,
            mapping_audit=f"name='{naam}' NIET in mapping-yaml — onboarding-blokker (D-03)",
        )

    def map_all(self, cleans: list[CleanRecord]) -> list[MappedRecord]:
        return [self.map_one(c) for c in cleans]


def collect_onboarding_errors(mapped: list[MappedRecord]) -> list[OnboardingError]:
    """Verzamel onbekende grootboek-codes als onboarding-blokkers (D-03)."""
    by_naam: dict[str, list[MappedRecord]] = defaultdict(list)
    for m in mapped:
        if m.mapping_method == MappingMethod.UNMAPPED:
            by_naam[m.clean.raw.pakket_grootboeknaam].append(m)

    errors = []
    for naam, recs in by_naam.items():
        first_3_ids = [r.clean.raw.bron_id for r in recs[:3]]
        first = recs[0].clean.raw
        errors.append(OnboardingError(
            pakket_grootboekcode=first.pakket_grootboekcode,
            pakket_grootboeknaam=naam,
            transactie_voorbeelden=first_3_ids,
            aantal_transacties=len(recs),
        ))
    return errors


def validate_administration(mapped: list[MappedRecord]) -> list[OnboardingError]:
    """Onboarding-validator. Lege lijst = klant kan live; non-leeg = blokkeren.

    D-03 conform: hard fail-discipline. Pipeline moet weigeren te starten als hier
    fouten uit komen.
    """
    return collect_onboarding_errors(mapped)
