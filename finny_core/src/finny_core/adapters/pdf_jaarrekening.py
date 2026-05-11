"""v7.2.0 - PDF-jaarrekening-adapter.

Doel: structureerde feiten extraheren uit NL-jaarrekening-PDF voor cross-check
op balans- en W&V-vragen. Niet "tekst extraheren" maar feiten:
  {post: 'liquide_middelen', periode: 2024, kolom: 'huidig_jaar', bedrag: 24417, bron: 'pdf p.7'}

ChatGPT-Lesson-3: tabelbewust werken. Niet alleen chunks ophalen, wel
financieel feit per regel structureren.

Voor v7.2.0: regel-gebaseerde extractie via regex op typische NL-jaarrekening
labels. Werkt voor SchilderwerkEZ-style PDF (gegenereerd uit standaard NL
RGS-jaarrekening-template). Bij andere stijlen: per-klant handmatige adapter.
"""
from __future__ import annotations
import re
import warnings
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

warnings.filterwarnings("ignore", category=DeprecationWarning)


class JaarrekeningPostExtraction(BaseModel):
    """Eén post uit een jaarrekening-PDF, structureerd."""
    post: str  # canonical key: 'liquide_middelen' / 'eigen_vermogen' / 'omzet' / etc.
    label: str  # rauwe label uit PDF: 'Liquide middelen' / 'Ondernemingsvermogen' etc.
    periode: int  # boekjaar
    kolom: str = "huidig_jaar"  # 'huidig_jaar' of 'vorig_jaar'
    bedrag: Decimal
    bron_pagina: int
    bron_regel: str  # rauwe regel-tekst voor audit


class JaarrekeningSnapshot(BaseModel):
    """Volledige extractie uit één PDF-jaarrekening."""
    klant_naam: str = ""
    boekjaar: int  # primaire jaar van deze jaarrekening
    bestand: str
    posts: list[JaarrekeningPostExtraction] = Field(default_factory=list)
    # Snelle lookups (canonical keys)
    eigen_vermogen_eind: Optional[Decimal] = None
    liquide_middelen_eind: Optional[Decimal] = None
    netto_omzet: Optional[Decimal] = None
    personeelskosten: Optional[Decimal] = None
    afschrijvingen: Optional[Decimal] = None
    totaal_activa: Optional[Decimal] = None
    extractie_warnings: list[str] = Field(default_factory=list)


# Regex-patronen voor typische NL-jaarrekening-regels
# Voorbeeld: "Liquide middelen  24.417   31.471"
# Voorbeeld: "Netto -omzet  81.580   76.007"
_NUMBER_PATTERN = r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?"
_RIGHT_TWO_NUMBERS = rf"({_NUMBER_PATTERN})\s+({_NUMBER_PATTERN})"

# Mapping van label-substring -> canonical post-key
LABEL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"liquide\s*middelen", re.I), "liquide_middelen_eind"),
    (re.compile(r"ondernemingsvermogen|eigen\s*vermogen|kapitaal\s*[A-Z]\.[A-Z]\.", re.I), "eigen_vermogen_eind"),
    (re.compile(r"netto\s*-?\s*omzet", re.I), "netto_omzet"),
    (re.compile(r"personeelskosten", re.I), "personeelskosten"),
    (re.compile(r"afschrijvingen", re.I), "afschrijvingen"),
    (re.compile(r"totaal\s*activa", re.I), "totaal_activa"),
    (re.compile(r"totaal\s*passiva", re.I), "totaal_passiva"),
    (re.compile(r"werkkapitaal", re.I), "werkkapitaal"),
]


def _parse_eu_number(s: str) -> Decimal:
    """Parse '24.417' of '24.417,50' (NL-format) of '-29' naar Decimal."""
    s = s.strip().replace(' ', '')
    if not s or s == '-':
        return Decimal('0')
    # NL: punt = duizendtal, komma = decimaal
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    else:
        # Geen komma — punten zijn duizendtallen
        s = s.replace('.', '')
    try:
        return Decimal(s)
    except Exception:
        return Decimal('0')


def extract_jaarrekening(pdf_path: Path, boekjaar: int, klant_naam: str = "") -> JaarrekeningSnapshot:
    """Hoofdfunctie: PDF inlezen + posts extraheren + snapshot bouwen.

    Args:
        pdf_path: pad naar PDF-bestand
        boekjaar: primair boekjaar van deze jaarrekening
        klant_naam: optioneel voor audit-trail
    """
    try:
        import pypdf
    except ImportError as e:
        snap = JaarrekeningSnapshot(boekjaar=boekjaar, bestand=str(pdf_path))
        snap.extractie_warnings.append(f"pypdf niet beschikbaar: {e}")
        return snap

    pdf = pypdf.PdfReader(str(pdf_path))
    snap = JaarrekeningSnapshot(klant_naam=klant_naam, boekjaar=boekjaar, bestand=str(pdf_path))

    # Sleutelposts die we al gevonden hebben (eerste vondst wint - voorkom dubbel)
    found_keys: set[str] = set()

    for page_idx, page in enumerate(pdf.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            snap.extractie_warnings.append(f"Page {page_idx+1} extract fail: {e}")
            continue

        for raw_line in text.split('\n'):
            line = ' '.join(raw_line.split())  # collapse whitespace
            if len(line) < 5 or not any(c.isdigit() for c in line):
                continue
            for pattern, post_key in LABEL_MAP:
                if not pattern.search(line):
                    continue
                # Extract twee getallen rechts in de regel
                m = re.search(_RIGHT_TWO_NUMBERS, line)
                if not m:
                    # Soms maar één getal (bv. vorig jaar = "-")
                    single = re.search(rf"({_NUMBER_PATTERN})", line)
                    if not single:
                        continue
                    huidig = _parse_eu_number(single.group(1))
                    vorig = None
                else:
                    huidig = _parse_eu_number(m.group(1))
                    vorig = _parse_eu_number(m.group(2))

                # Alleen eerste vondst per key registreren (header-row vs detail-row)
                lookup_key = f"{post_key}__{boekjaar}"
                if lookup_key in found_keys:
                    continue
                found_keys.add(lookup_key)

                snap.posts.append(JaarrekeningPostExtraction(
                    post=post_key, label=line[:60], periode=boekjaar,
                    kolom="huidig_jaar", bedrag=huidig, bron_pagina=page_idx + 1,
                    bron_regel=line[:120],
                ))
                if vorig is not None:
                    snap.posts.append(JaarrekeningPostExtraction(
                        post=post_key, label=line[:60], periode=boekjaar - 1,
                        kolom="vorig_jaar", bedrag=vorig, bron_pagina=page_idx + 1,
                        bron_regel=line[:120],
                    ))
                # Snelle lookup vullen
                if post_key == "liquide_middelen_eind":
                    snap.liquide_middelen_eind = huidig
                elif post_key == "eigen_vermogen_eind":
                    snap.eigen_vermogen_eind = huidig
                elif post_key == "netto_omzet":
                    snap.netto_omzet = huidig
                elif post_key == "personeelskosten":
                    snap.personeelskosten = huidig
                elif post_key == "afschrijvingen":
                    snap.afschrijvingen = huidig
                elif post_key == "totaal_activa":
                    snap.totaal_activa = huidig

    if not found_keys:
        snap.extractie_warnings.append("Geen bekende posts gevonden — PDF mogelijk afwijkend format")
    return snap
