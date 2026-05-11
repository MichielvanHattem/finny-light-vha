"""Bron-adapter voor e-Boekhouden / Exact Online CSV-export.

Laag 1: ruwe data → list[RawRecord].
Detecteert encoding (UTF-16-LE BOM, UTF-8-BOM, UTF-8) — geleerd uit SchilderwerkEZ data.
"""
from __future__ import annotations
from datetime import date as Date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
import pandas as pd

from ..models import RawRecord, Bron


def detect_encoding(path: Path) -> str:
    """Detecteer file-encoding o.b.v. BOM. Lesson #51 — eigen detectie nodig."""
    with open(path, 'rb') as f:
        head = f.read(4)
    if head.startswith(b'\xff\xfe'):
        return 'utf-16-le'
    if head.startswith(b'\xfe\xff'):
        return 'utf-16-be'
    if head.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    return 'utf-8'


def parse_nl_decimal(s: str) -> Decimal:
    """NL-format '1.234,56' of '-8,56' → Decimal('1234.56')."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return Decimal('0')
    s = str(s).strip()
    if not s or s.lower() == 'nan':
        return Decimal('0')
    # Verwijder duizendpunten waar gevolgd door 3 cijfers
    import re
    s = re.sub(r'\.(\d{3})(?!\d)', r'\1', s)
    s = s.replace(',', '.')
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal('0')


def parse_nl_date(s: str) -> Date:
    """NL-format 'D-M-YYYY' of 'DD-MM-YYYY' → Date."""
    if s is None: raise ValueError("Lege datum")
    s = str(s).strip()
    for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Datumformaat niet herkend: {s!r}")


class ExactOnlineCSVAdapter:
    """SchilderwerkEZ FinTransactionSearch-format. Tab-delimited, UTF-16-LE meestal."""
    bron = Bron.EXACT_CSV

    def read_file(self, path: Path) -> pd.DataFrame:
        enc = detect_encoding(path)
        return pd.read_csv(path, encoding=enc, sep='\t')

    def to_records(self, path: Path) -> list[RawRecord]:
        df = self.read_file(path)
        records = []
        for idx, row in df.iterrows():
            try:
                bedrag = parse_nl_decimal(row.get('AmountDC', '0'))
                if bedrag == 0:
                    continue  # skip lege regels
                d = parse_nl_date(row.get('EntryDate'))
                jaar = int(row.get('ReportingYear', d.year)) if not pd.isna(row.get('ReportingYear')) else d.year
                rec = RawRecord(
                    bron=self.bron,
                    bron_id=f"{path.stem}#{row.get('EntryNumber', idx)}",
                    datum=d,
                    bedrag=bedrag,
                    omschrijving=str(row.get('Description', '') or ''),
                    pakket_grootboekcode=str(row.get('GLAccountCodeDescription', row.get('AccountCode', ''))),
                    pakket_grootboeknaam=str(row.get('GLAccountDescriptionDescription', '')),
                    journaal_code=str(row.get('JournalCode', '')) if not pd.isna(row.get('JournalCode')) else None,
                    journaal_naam=str(row.get('JournalCodeDescriptionDescription', '')),
                    factuur_ref=str(row.get('InvoiceNumber', '')) if not pd.isna(row.get('InvoiceNumber')) else None,
                    btw_percentage=parse_nl_decimal(str(row.get('VATPercentage', '0'))) if not pd.isna(row.get('VATPercentage')) else None,
                    extra={'reporting_year': jaar, 'reporting_period': int(row.get('ReportingPeriod', d.month)) if not pd.isna(row.get('ReportingPeriod')) else d.month},
                )
                records.append(rec)
            except (ValueError, KeyError) as e:
                # Log maar gooi niet weg
                continue
        return records

    def read_directory(self, dir_path: Path, pattern: str = "*.csv") -> list[RawRecord]:
        out = []
        for p in sorted(Path(dir_path).glob(pattern)):
            out.extend(self.to_records(p))
        return out
