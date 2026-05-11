"""Laag 6: berekening-engine - pure Python, deterministisch, GEEN LLM.

v7.1.0: ChatGPT-sparring-feedback verwerkt:
- SourceQuality uitgebreid met opening_balance_verified, source_type, structured_source.
- ConfidenceLabel-bepaling herzien: HIGH_VERIFIED / HIGH_SINGLE_SOURCE / MEDIUM / LOW / NONE.
- Q03 second-layer: filter combineert JC + RGS-categorie + balans/W&V-check
  (niet alleen JournalCode — ChatGPT-correctie op te-strikte-L-030).

D-01: Sandwich-pattern.
D-02: default + alternative_definitions.
D-03: 100% RGS-mapping verplicht.
D-05: MKB-light-categorieen.
D-06: AnswerMode + missing_sources (ChatGPT-Lesson-6).
D-07: SourceQuality (ChatGPT-Lesson-10).

Filter-discipline (L-029 + L-030 herformulering):
  W&V-omzet: Verkoopboek (70).
  W&V-bedrijfslasten: Inkoop+Bank+Transitoria [20,21,60,99] EN niet
    activamutatie/btw/balans EN RGS-categorie WV_BEDRIJFSLASTEN.
    Niet alleen op JC filteren -- combineer met RGS-categorie en
    debet/credit-richting (L-030 herformulering).
  Balans-saldi: vereisen opening_balance_verified=True voor ANSWERED.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional
from ..models import (
    MappedRecord, CalculationResult, DefinitionChoice, IntentType,
    AnswerMode, MissingSource, SourceQuality, ConfidenceLabel, SourceType,
    SourceFreshness, Bron, RGSCategory,
)
from ..mkb_light.categorize import MKBCategorie, categorize_mkb


EXPENSE_JOURNAL_CODES = ['20', '21', '60', '99']
SALES_JOURNAL_CODES = ['70']
PURCHASE_JOURNAL_CODES = ['60']

# RGS-categorieen die ECHT W&V-bedrijfslasten zijn (L-030 herformulering)
WV_EXPENSE_RGS_CATEGORIES = {
    RGSCategory.WV_BEDRIJFSLASTEN,
    RGSCategory.WV_KOSTPRIJS,
}
BALANCE_RGS_CATEGORIES = {
    RGSCategory.BALANS_ACTIVA,
    RGSCategory.BALANS_PASSIVA_EV,
    RGSCategory.BALANS_PASSIVA_VV,
}


def _records_in_category(mapped, cat, jaar=None, journaal_codes=None):
    out = []
    for m in mapped:
        if categorize_mkb(m) != cat:
            continue
        if jaar is not None and m.clean.boekjaar != jaar:
            continue
        if journaal_codes is not None:
            jc = m.clean.raw.journaal_code
            if jc not in journaal_codes:
                continue
        out.append(m)
    return out


def _is_real_expense(m: MappedRecord) -> bool:
    """L-030 herformulering: een record is een echte W&V-kost als (a) JC in
    EXPENSE_JOURNAL_CODES OF (b) JC in memoriaal MAAR RGS-categorie is
    WV_BEDRIJFSLASTEN/WV_KOSTPRIJS EN debet-zijde EN niet btw/bank/balans.

    Voorkomt dat memoriaal-eindejaarscorrecties die echte kosten zijn
    (afschrijving, loon, accountant-correctie) ten onrechte uitgesloten worden.
    """
    if m.rgs_code is None:
        return False
    rgs_cat = m.rgs_code.categorie
    # NIET: balans, btw, financieel, belasting
    if rgs_cat in BALANCE_RGS_CATEGORIES:
        return False
    if rgs_cat == RGSCategory.MEMO:
        return False
    # WEL: bedrijfslasten of kostprijs
    if rgs_cat not in WV_EXPENSE_RGS_CATEGORIES:
        return False
    jc = m.clean.raw.journaal_code or ''
    if jc in EXPENSE_JOURNAL_CODES:
        return True
    # Memoriaal (90) ALLEEN als debet-zijde EN niet zelf-uitmiddelend
    if jc == '90' and m.clean.bedrag_eur > 0:
        # Echte kostmutatie via memoriaal (afschrijving, loonjournaal, accountant-correctie)
        return True
    # Activamutatie (80) NIET — die zijn zelf-uitmiddelend
    return False


def _sum_bedrag(records):
    return sum((m.clean.bedrag_eur for m in records), Decimal('0'))


def _flip(d):
    return -d


def _heeft_beginsaldo(mapped, categorie):
    """Detectie: eerste-record-datum in deze categorie <= 1-jan-eerste-boekjaar.
    ChatGPT-waarschuwing: dit is alleen een MINIMUMSIGNAAL. False = beginsaldo
    ontbreekt zeker. True != automatisch ANSWERED — opening_balance_verified
    moet via PDF/auditfile/voorgaand-jaar-saldo expliciet worden bevestigd.
    """
    cat_records = [m for m in mapped if categorize_mkb(m) == categorie]
    if not cat_records:
        return (False, None)
    eerste_datum = min(m.clean.raw.datum for m in cat_records)
    eerste_jaar = min(m.clean.boekjaar for m in cat_records)
    eerste_jan = date(eerste_jaar, 1, 1)
    return (eerste_datum <= eerste_jan, eerste_datum)


def _determine_confidence_label(
    *, period_match, metric_match, amount_found,
    cross_checked, structured_source, opening_balance_required, opening_balance_verified,
    mode: AnswerMode,
) -> ConfidenceLabel:
    """v7.1.0: ChatGPT-correctie split HIGH_VERIFIED vs HIGH_SINGLE_SOURCE.

    Praktische regel:
      REFUSED → NONE
      cross_checked + alle matches → HIGH_VERIFIED
      structured_source + period+metric+amount + (geen balans-vraag of opening_verified) → HIGH_SINGLE_SOURCE
      data aanwezig, structured, maar PARTIAL of cross_check-ontbreekt → MEDIUM
      anders → LOW
    """
    if mode == AnswerMode.REFUSED:
        return ConfidenceLabel.NONE
    all_match = period_match and metric_match and amount_found
    if cross_checked and all_match:
        return ConfidenceLabel.HIGH_VERIFIED
    if all_match and structured_source:
        # Voor balans-vragen: opening_balance_verified vereist voor HIGH
        if opening_balance_required and not opening_balance_verified:
            return ConfidenceLabel.MEDIUM
        return ConfidenceLabel.HIGH_SINGLE_SOURCE
    if mode == AnswerMode.PARTIAL:
        return ConfidenceLabel.MEDIUM if all_match else ConfidenceLabel.LOW
    return ConfidenceLabel.LOW


def _build_source_quality(
    *, period_match, metric_match, amount_found,
    journal_codes_used, journal_codes_excluded=None,
    cross_checked=False, notes=None,
    opening_balance_verified=False,
    source_type: SourceType = SourceType.TRANSACTIONS_CSV,
    structured_source: bool = True,
    conflicting_sources_found: bool = False,
    source_freshness: SourceFreshness = SourceFreshness.UNKNOWN,
    opening_balance_required: bool = False,
    mode: AnswerMode = AnswerMode.ANSWERED,
) -> SourceQuality:
    label = _determine_confidence_label(
        period_match=period_match, metric_match=metric_match, amount_found=amount_found,
        cross_checked=cross_checked, structured_source=structured_source,
        opening_balance_required=opening_balance_required,
        opening_balance_verified=opening_balance_verified, mode=mode,
    )
    return SourceQuality(
        period_match=period_match, metric_match=metric_match, amount_found=amount_found,
        journal_codes_used=journal_codes_used,
        journal_codes_excluded=journal_codes_excluded or [],
        cross_checked=cross_checked,
        confidence_label=label,
        quality_notes=notes or [],
        opening_balance_verified=opening_balance_verified,
        source_type=source_type,
        structured_source=structured_source,
        conflicting_sources_found=conflicting_sources_found,
        source_freshness=source_freshness,
    )


def _refused_result(intent, label, missing_sources, quality_notes, eenheid="EUR"):
    return CalculationResult(
        intent=intent,
        default_definition=DefinitionChoice(
            label=label, value=Decimal('0'), bron_records_count=0, bron_rgs_codes=[],
        ),
        eenheid=eenheid, cross_check_passed=False, cross_check_notes=quality_notes,
        confidence=0.0, mode=AnswerMode.REFUSED, missing_sources=missing_sources,
        source_quality=_build_source_quality(
            period_match=False, metric_match=True, amount_found=False,
            journal_codes_used=[], notes=quality_notes,
            source_type=SourceType.NONE, structured_source=True,
            mode=AnswerMode.REFUSED,
        ),
    )


def omzet(mapped, jaar):
    verkoop = _records_in_category(mapped, MKBCategorie.OMZET, jaar=jaar, journaal_codes=SALES_JOURNAL_CODES)
    if len(verkoop) == 0:
        return _refused_result(
            intent=IntentType.RESULT,
            label=f"Omzet {jaar} - geen records gevonden",
            missing_sources=[MissingSource(
                bron_type=Bron.EXACT_CSV,
                bestand_hint=f"FinTransactionSearch_{jaar}.csv",
                reden=f"Geen verkoopboek-records (JC=70) voor {jaar}.",
                kritiek=True,
            )],
            quality_notes=[f"Geen verkoopboek-mutaties voor {jaar}."],
        )
    netto = _flip(_sum_bedrag(verkoop))
    default = DefinitionChoice(
        label=f"Netto-omzet {jaar} (RGS opbrengsten via verkoopboek)",
        value=netto, bron_records_count=len(verkoop),
        bron_rgs_codes=sorted(set(m.rgs_code.code for m in verkoop if m.rgs_code)),
    )
    fin_baten = _records_in_category(mapped, MKBCategorie.FINANCIEEL, jaar=jaar)
    fin_baten = [m for m in fin_baten if m.clean.bedrag_eur < 0]
    bruto = netto + _flip(_sum_bedrag(fin_baten))
    alternatives = []
    if netto > 0 and abs(bruto - netto) > netto * Decimal('0.05'):
        alternatives.append(DefinitionChoice(
            label=f"Omzet {jaar} inclusief overige opbrengsten",
            value=bruto, bron_records_count=len(verkoop) + len(fin_baten),
            bron_rgs_codes=sorted(set((m.rgs_code.code if m.rgs_code else '?') for m in verkoop + fin_baten)),
        ))
    return CalculationResult(
        intent=IntentType.RESULT,
        default_definition=default, alternative_definitions=alternatives, eenheid="EUR",
        cross_check_passed=netto > 0,
        cross_check_notes=[] if netto > 0 else ["WAARSCHUWING: netto-omzet niet positief"],
        mode=AnswerMode.ANSWERED,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=netto > 0,
            journal_codes_used=SALES_JOURNAL_CODES, journal_codes_excluded=['90'],
            cross_checked=False,
            notes=[
                "Verkoopboek (JC=70), excl memoriaal-eindejaarscorrecties (JC=90, L-030).",
                f"Netto-omzet; bruto-omzet alt {'getoond' if alternatives else 'niet relevant'}.",
            ],
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_required=False, mode=AnswerMode.ANSWERED,
        ),
    )


def totale_kosten(mapped, jaar):
    """Q03 - L-030 herformulering: filter combineert JC + RGS-categorie + debet-richting.
    Niet alleen op JournalCode filteren (ChatGPT-correctie 9 mei middag).
    """
    cats_excl = [
        MKBCategorie.PERSONEELSKOSTEN, MKBCategorie.HUISVESTINGSKOSTEN,
        MKBCategorie.VERKOOPKOSTEN, MKBCategorie.AUTOKOSTEN,
        MKBCategorie.ALGEMENE_KOSTEN, MKBCategorie.AFSCHRIJVINGEN,
    ]
    # SECOND-LAYER: gebruik _is_real_expense (combineert JC + RGS-categorie + debet)
    excl_records = []
    for cat in cats_excl:
        for m in _records_in_category(mapped, cat, jaar=jaar):
            if _is_real_expense(m):
                excl_records.append(m)
    excl_total = _sum_bedrag(excl_records)
    if len(excl_records) == 0:
        return _refused_result(
            intent=IntentType.TOTAL_COST,
            label=f"Totale kosten {jaar} - geen bedrijfslasten-records",
            missing_sources=[MissingSource(
                bron_type=Bron.EXACT_CSV,
                bestand_hint=f"FinTransactionSearch_{jaar}.csv",
                reden=f"Geen bedrijfslasten-records voor {jaar}.", kritiek=True,
            )],
            quality_notes=[f"Geen records in MKB-bedrijfslasten voor {jaar}."],
        )
    default = DefinitionChoice(
        label=f"Bedrijfslasten {jaar} (excl kostprijs, JC+RGS+debet-filter)",
        value=excl_total, bron_records_count=len(excl_records),
        bron_rgs_codes=sorted(set(m.rgs_code.code for m in excl_records if m.rgs_code)),
    )
    # Alternatief: incl kostprijs
    kostprijs_recs = []
    for m in _records_in_category(mapped, MKBCategorie.KOSTPRIJS_OMZET, jaar=jaar):
        if _is_real_expense(m):
            kostprijs_recs.append(m)
    incl_total = excl_total + _sum_bedrag(kostprijs_recs)
    alternatives = []
    if excl_total > 0 and abs(incl_total - excl_total) / excl_total > Decimal('0.05'):
        alternatives.append(DefinitionChoice(
            label=f"Som der bedrijfslasten {jaar} (incl kostprijs)",
            value=incl_total, bron_records_count=len(excl_records) + len(kostprijs_recs),
            bron_rgs_codes=sorted(set((m.rgs_code.code if m.rgs_code else '?') for m in excl_records + kostprijs_recs)),
        ))
    afschrijvingen = _records_in_category(mapped, MKBCategorie.AFSCHRIJVINGEN, jaar=jaar)
    huisvesting = _records_in_category(mapped, MKBCategorie.HUISVESTINGSKOSTEN, jaar=jaar)
    quality_notes = [
        "Filter: JC in [20,21,60,99] OF (JC=90 EN debet EN RGS=W&V-bedrijfslasten).",
        "L-030 herformulering: memoriaal niet automatisch uitsluiten — alleen als activa/btw/balans.",
    ]
    missing = []
    mode = AnswerMode.ANSWERED
    if not afschrijvingen and not huisvesting:
        mode = AnswerMode.PARTIAL
        quality_notes.append("Geen records voor afschrijvingen+huisvestingskosten — mogelijk in PDF.")
        missing.append(MissingSource(
            bron_type=Bron.PDF_JAARREKENING, bestand_hint=f"jaarrekening_{jaar}.pdf",
            reden="Afschrijvingen+huisvesting ontbreken in CSV; PDF voor cross-check.",
            kritiek=False,
        ))
    return CalculationResult(
        intent=IntentType.TOTAL_COST,
        default_definition=default, alternative_definitions=alternatives, eenheid="EUR",
        cross_check_passed=True, mode=mode, missing_sources=missing,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=excl_total > 0,
            journal_codes_used=EXPENSE_JOURNAL_CODES + (['90-debet-only'] if any(m.clean.raw.journaal_code == '90' for m in excl_records) else []),
            journal_codes_excluded=['80', '90-credit-balans-correcties'],
            cross_checked=False, notes=quality_notes,
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_required=False, mode=mode,
        ),
    )


def liquide_middelen_eind(mapped, jaar):
    beginsaldo_ok, eerste_datum = _heeft_beginsaldo(mapped, MKBCategorie.LIQUIDE_MIDDELEN)
    relevant = [
        m for m in mapped
        if categorize_mkb(m) == MKBCategorie.LIQUIDE_MIDDELEN
        and m.clean.boekjaar <= jaar
        and 'kruispost' not in (m.rgs_code.naam or '').lower()
    ]
    if not relevant:
        return _refused_result(
            intent=IntentType.BALANCE,
            label=f"Liquide middelen einde {jaar} - geen records",
            missing_sources=[MissingSource(
                bron_type=Bron.PDF_JAARREKENING, bestand_hint=f"jaarrekening_{jaar}.pdf",
                reden="Geen liquide-middelen-mutaties.", kritiek=True,
            )],
            quality_notes=[f"Geen banksaldo-records voor of in {jaar}."],
        )
    cum_default = _sum_bedrag(relevant)
    default = DefinitionChoice(
        label=f"Liquide middelen einde {jaar} (bank+spaar, cumulatief, excl kruisposten)",
        value=cum_default, bron_records_count=len(relevant),
        bron_rgs_codes=sorted(set(m.rgs_code.code for m in relevant if m.rgs_code)),
    )
    relevant_incl = [
        m for m in mapped
        if categorize_mkb(m) == MKBCategorie.LIQUIDE_MIDDELEN and m.clean.boekjaar <= jaar
    ]
    incl = _sum_bedrag(relevant_incl)
    alternatives = []
    if cum_default != 0 and abs(incl - cum_default) / abs(cum_default) > Decimal('0.05'):
        alternatives.append(DefinitionChoice(
            label=f"Liquide middelen einde {jaar} incl kruisposten",
            value=incl, bron_records_count=len(relevant_incl),
            bron_rgs_codes=sorted(set((m.rgs_code.code if m.rgs_code else '?') for m in relevant_incl)),
        ))
    quality_notes = []
    missing = []
    mode = AnswerMode.ANSWERED
    # ChatGPT-regel: opening_balance_verified is kritiek; alleen first_record_date <= 1-jan
    # is onvoldoende voor ANSWERED. Hier zonder PDF-anker is verified=False.
    opening_balance_verified = False  # tot v7.2.0 PDF-adapter
    if not beginsaldo_ok:
        mode = AnswerMode.PARTIAL
        quality_notes.append(
            f"Beginsaldo per 1-1-{eerste_datum.year} ontbreekt (eerste record {eerste_datum.isoformat()}). "
            "Cumulatieve saldo niet betrouwbaar."
        )
        missing.append(MissingSource(
            bron_type=Bron.PDF_JAARREKENING,
            bestand_hint=f"jaarrekening_{eerste_datum.year - 1}.pdf",
            reden=f"Beginsaldo banksaldo per 1-1-{eerste_datum.year}.", kritiek=True,
        ))
    elif not opening_balance_verified:
        # ChatGPT: zelfs bij first_record == 1-1 mag ANSWERED niet automatisch
        mode = AnswerMode.PARTIAL
        quality_notes.append(
            "Eerste record op 1-1 maar geen opening_balance_verified-anker uit "
            "PDF/auditfile/voorgaand-jaar-saldo. Verifiëren vóór ANSWERED."
        )
        missing.append(MissingSource(
            bron_type=Bron.PDF_JAARREKENING, bestand_hint=f"jaarrekening_{jaar - 1}.pdf",
            reden="Opening_balance_verified-anker ontbreekt.", kritiek=False,
        ))
    if cum_default < 0:
        if mode == AnswerMode.ANSWERED:
            mode = AnswerMode.PARTIAL
        quality_notes.append(
            f"Berekend saldo {cum_default:,.2f} negatief - fysiek onwaarschijnlijk voor banksaldo."
        )
    return CalculationResult(
        intent=IntentType.BALANCE,
        default_definition=default, alternative_definitions=alternatives, eenheid="EUR",
        cross_check_passed=cum_default >= 0, cross_check_notes=quality_notes,
        confidence=0.5 if mode == AnswerMode.PARTIAL else 1.0,
        mode=mode, missing_sources=missing,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=cum_default >= 0,
            journal_codes_used=['20', '21', '90', '99'], cross_checked=False, notes=quality_notes,
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_verified=opening_balance_verified, opening_balance_required=True,
            mode=mode,
        ),
    )


def eigen_vermogen_eind(mapped, jaar):
    beginsaldo_ok, eerste_datum = _heeft_beginsaldo(mapped, MKBCategorie.EIGEN_VERMOGEN)
    relevant = [m for m in mapped if categorize_mkb(m) == MKBCategorie.EIGEN_VERMOGEN and m.clean.boekjaar <= jaar]
    if not relevant:
        return _refused_result(
            intent=IntentType.BALANCE,
            label=f"Eigen vermogen einde {jaar} - geen records",
            missing_sources=[MissingSource(
                bron_type=Bron.PDF_JAARREKENING, bestand_hint=f"jaarrekening_{jaar}.pdf",
                reden="Geen kapitaal-records.", kritiek=True,
            )],
            quality_notes=[f"Geen mutaties op eigen vermogen voor of in {jaar}."],
        )
    cum = _flip(_sum_bedrag(relevant))
    default = DefinitionChoice(
        label=f"Eigen vermogen einde {jaar} (kapitaal+mutaties cumulatief)",
        value=cum, bron_records_count=len(relevant),
        bron_rgs_codes=sorted(set(m.rgs_code.code for m in relevant if m.rgs_code)),
    )
    quality_notes = []
    missing = []
    mode = AnswerMode.ANSWERED
    opening_balance_verified = False
    if not beginsaldo_ok:
        mode = AnswerMode.PARTIAL
        quality_notes.append(
            f"Beginsaldo per 1-1-{eerste_datum.year} (kapitaal-inleg) ontbreekt "
            f"(eerste record {eerste_datum.isoformat()}). Cumulatieve EV niet betrouwbaar."
        )
        missing.append(MissingSource(
            bron_type=Bron.PDF_JAARREKENING,
            bestand_hint=f"jaarrekening_{eerste_datum.year - 1}.pdf",
            reden=f"Beginbalans EV per 1-1-{eerste_datum.year}.", kritiek=True,
        ))
    elif not opening_balance_verified:
        mode = AnswerMode.PARTIAL
        quality_notes.append(
            "Eerste record op 1-1 maar opening_balance_verified-anker ontbreekt. "
            "Verifiëren via PDF-jaarrekening of voorgaand-jaar-balans vóór ANSWERED."
        )
        missing.append(MissingSource(
            bron_type=Bron.PDF_JAARREKENING, bestand_hint=f"jaarrekening_{jaar - 1}.pdf",
            reden="Opening_balance_verified-anker EV ontbreekt.", kritiek=False,
        ))
    return CalculationResult(
        intent=IntentType.BALANCE,
        default_definition=default, alternative_definitions=[], eenheid="EUR",
        cross_check_passed=True, cross_check_notes=quality_notes,
        confidence=0.5 if mode == AnswerMode.PARTIAL else 1.0,
        mode=mode, missing_sources=missing,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=cum != 0,
            journal_codes_used=sorted(set(m.clean.raw.journaal_code or '?' for m in relevant)),
            cross_checked=False, notes=quality_notes,
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_verified=opening_balance_verified, opening_balance_required=True,
            mode=mode,
        ),
    )


def brutomarge_bedrag(mapped, jaar):
    omzet_calc = omzet(mapped, jaar)
    if omzet_calc.mode == AnswerMode.REFUSED:
        return _refused_result(
            intent=IntentType.RATIO,
            label=f"Brutomarge {jaar} - omzet niet beschikbaar",
            missing_sources=omzet_calc.missing_sources,
            quality_notes=[f"Brutomarge vereist omzet; omzet={omzet_calc.mode.value}."],
        )
    kostprijs_recs = _records_in_category(mapped, MKBCategorie.KOSTPRIJS_OMZET, jaar=jaar, journaal_codes=PURCHASE_JOURNAL_CODES)
    kostprijs_totaal = _sum_bedrag(kostprijs_recs)
    bm = omzet_calc.default_definition.value - kostprijs_totaal
    default = DefinitionChoice(
        label=f"Brutomarge {jaar} (netto-omzet minus kostprijs)",
        value=bm,
        bron_records_count=omzet_calc.default_definition.bron_records_count + len(kostprijs_recs),
        bron_rgs_codes=omzet_calc.default_definition.bron_rgs_codes + [m.rgs_code.code for m in kostprijs_recs if m.rgs_code],
    )
    return CalculationResult(
        intent=IntentType.RATIO,
        default_definition=default, alternative_definitions=[], eenheid="EUR",
        mode=omzet_calc.mode, missing_sources=omzet_calc.missing_sources,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=bm > 0,
            journal_codes_used=SALES_JOURNAL_CODES + PURCHASE_JOURNAL_CODES,
            cross_checked=False,
            notes=["Omzet uit verkoopboek (70), kostprijs uit inkoopboek (60)."],
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_required=False, mode=omzet_calc.mode,
        ),
    )


def brutomarge_pct(mapped, jaar):
    bm_eur = brutomarge_bedrag(mapped, jaar)
    if bm_eur.mode == AnswerMode.REFUSED:
        return _refused_result(
            intent=IntentType.RATIO,
            label=f"Brutomarge% {jaar} - onderliggende brutomarge niet beschikbaar",
            missing_sources=bm_eur.missing_sources,
            quality_notes=bm_eur.cross_check_notes, eenheid="%",
        )
    omzet_calc = omzet(mapped, jaar)
    omz = omzet_calc.default_definition.value
    pct = (bm_eur.default_definition.value / omz * Decimal('100')) if omz else Decimal('0')
    default = DefinitionChoice(
        label=f"Brutomarge percentage {jaar}",
        value=pct.quantize(Decimal('0.01')),
        bron_records_count=bm_eur.default_definition.bron_records_count,
        bron_rgs_codes=bm_eur.default_definition.bron_rgs_codes,
    )
    return CalculationResult(
        intent=IntentType.RATIO,
        default_definition=default, alternative_definitions=[], eenheid="%",
        mode=bm_eur.mode, missing_sources=bm_eur.missing_sources,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=pct > 0,
            journal_codes_used=SALES_JOURNAL_CODES + PURCHASE_JOURNAL_CODES,
            cross_checked=False, notes=[f"Brutomarge%={pct.quantize(Decimal('0.01'))}%."],
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_required=False, mode=bm_eur.mode,
        ),
    )


def omzet_per_jaar(mapped, jaren):
    per_jaar = {}
    sub_modes = []
    sub_missing = []
    total_records = 0
    for j in jaren:
        sub = omzet(mapped, j)
        per_jaar[j] = sub.default_definition.value
        sub_modes.append(sub.mode)
        sub_missing.extend(sub.missing_sources)
        total_records += sub.default_definition.bron_records_count
    default = DefinitionChoice(
        label=f"Omzet per jaar {jaren[0]}-{jaren[-1]}",
        value={str(j): str(v) for j, v in per_jaar.items()},
        bron_records_count=total_records, bron_rgs_codes=[],
    )
    if AnswerMode.REFUSED in sub_modes:
        mode = AnswerMode.PARTIAL
    elif AnswerMode.PARTIAL in sub_modes:
        mode = AnswerMode.PARTIAL
    else:
        mode = AnswerMode.ANSWERED
    return CalculationResult(
        intent=IntentType.TREND,
        default_definition=default, eenheid="EUR",
        mode=mode, missing_sources=sub_missing,
        source_quality=_build_source_quality(
            period_match=True, metric_match=True, amount_found=total_records > 0,
            journal_codes_used=SALES_JOURNAL_CODES, cross_checked=False,
            notes=[f"Trend over {jaren}, mode per jaar: {[m.value for m in sub_modes]}"],
            source_type=SourceType.TRANSACTIONS_CSV, structured_source=True,
            opening_balance_required=False, mode=mode,
        ),
    )


# ============================================================
# v7.2.0 - PDF cross-check helpers
# ============================================================

def cross_check_with_pdf(calc: CalculationResult, pdf_snapshot, post_key: str) -> CalculationResult:
    """Verrijk een CalculationResult met PDF-jaarrekening-anker.

    Als PDF-snapshot een bedrag heeft voor de gevraagde post:
    - mode wordt ANSWERED (was PARTIAL)
    - default_definition wordt VERVANGEN door PDF-bedrag (PDF is leidend voor balans)
    - alternative_definition krijgt het CSV-cumulatief-cijfer met label "CSV mutaties (zonder beginsaldo)"
    - source_quality.cross_checked = True
    - source_quality.opening_balance_verified = True (indirect, want PDF heeft balans)
    - confidence_label wordt opnieuw bepaald → HIGH_VERIFIED

    Args:
        calc: bestaande CalculationResult (mode=PARTIAL meestal)
        pdf_snapshot: JaarrekeningSnapshot
        post_key: 'eigen_vermogen_eind' / 'liquide_middelen_eind' / 'netto_omzet'
    """
    pdf_value = getattr(pdf_snapshot, post_key, None)
    if pdf_value is None:
        return calc  # geen PDF-data → ongewijzigd

    csv_value = calc.default_definition.value
    new_default = DefinitionChoice(
        label=f"{post_key.replace('_', ' ').title()} (uit PDF jaarrekening, primaire bron)",
        value=pdf_value,
        bron_records_count=1,
        bron_rgs_codes=[f"PDF:{pdf_snapshot.bestand}"],
    )
    new_alts = list(calc.alternative_definitions)
    new_alts.insert(0, DefinitionChoice(
        label=f"{post_key.replace('_', ' ').title()} (CSV mutaties, zonder beginsaldo)",
        value=csv_value,
        bron_records_count=calc.default_definition.bron_records_count,
        bron_rgs_codes=calc.default_definition.bron_rgs_codes,
    ))

    # Source quality update — cross_checked + opening_balance_verified=True
    sq = calc.source_quality
    new_notes = list(sq.quality_notes) if sq else []
    new_notes.insert(0, f"PDF-cross-check: {post_key} = EUR {pdf_value:,.2f} (uit {pdf_snapshot.bestand})")
    if sq and abs(pdf_value - csv_value) > Decimal('100'):
        new_notes.append(
            f"Verschil PDF vs CSV-cumulatief: EUR {abs(pdf_value - csv_value):,.2f} "
            f"(typisch door ontbrekend beginsaldo of memoriaal-correcties)"
        )
    new_sq = _build_source_quality(
        period_match=True, metric_match=True, amount_found=True,
        journal_codes_used=(sq.journal_codes_used if sq else []) + ['PDF'],
        journal_codes_excluded=(sq.journal_codes_excluded if sq else []),
        cross_checked=True,
        notes=new_notes,
        opening_balance_verified=True,  # PDF is per definitie balans-anker
        source_type=SourceType.ANNUAL_STATEMENT_PDF,
        structured_source=False,  # PDF-tekst-extractie is semi-structured
        conflicting_sources_found=abs(pdf_value - csv_value) > Decimal('100'),
        opening_balance_required=True,
        mode=AnswerMode.ANSWERED,
    )

    return CalculationResult(
        intent=calc.intent,
        default_definition=new_default,
        alternative_definitions=new_alts,
        eenheid=calc.eenheid,
        cross_check_passed=True,
        cross_check_notes=new_notes,
        confidence=1.0,
        mode=AnswerMode.ANSWERED,
        missing_sources=[],  # PDF heeft missing source ingevuld
        source_quality=new_sq,
    )
