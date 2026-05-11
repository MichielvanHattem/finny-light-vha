"""MKB-light categorisering — 22 categorieen (D-05 ChatGPT-spec)."""
from __future__ import annotations
from enum import Enum
from ..models import RGSCategory, MappedRecord


class MKBCategorie(str, Enum):
    # W&V
    OMZET = "omzet"
    OVERIGE_OPBRENGSTEN = "overige_opbrengsten"
    KOSTPRIJS_OMZET = "kostprijs_omzet"
    PERSONEELSKOSTEN = "personeelskosten"
    HUISVESTINGSKOSTEN = "huisvestingskosten"
    VERKOOPKOSTEN = "verkoopkosten"
    AUTOKOSTEN = "autokosten"
    ALGEMENE_KOSTEN = "algemene_kosten"
    AFSCHRIJVINGEN = "afschrijvingen"
    FINANCIEEL = "financieel_resultaat"
    BELASTINGEN = "belastingen"
    PRIVE = "prive"

    # Balans
    VASTE_ACTIVA = "vaste_activa"
    VLOTTENDE_ACTIVA = "vlottende_activa"
    DEBITEUREN = "debiteuren"
    LIQUIDE_MIDDELEN = "liquide_middelen"
    EIGEN_VERMOGEN = "eigen_vermogen"
    SCHULDEN_KORT = "schulden_kort"
    SCHULDEN_LANG = "schulden_lang"
    BTW = "btw"
    INVESTERINGEN = "investeringen"

    # Niet ingedeeld
    OVERIG = "overig"


# Heuristiek: RGS-naam-substring → MKB-categorie
# Specifiek vóór algemeen — eerste match wint
_NAME_RULES: list[tuple[str, MKBCategorie]] = [
    # Auto
    ("vervoermiddel", MKBCategorie.AUTOKOSTEN),
    ("auto", MKBCategorie.AUTOKOSTEN),
    ("brandstof", MKBCategorie.AUTOKOSTEN),
    ("motorrijtuig", MKBCategorie.AUTOKOSTEN),
    # Verkoop
    ("verkoop", MKBCategorie.VERKOOPKOSTEN),
    ("reclame", MKBCategorie.VERKOOPKOSTEN),
    ("relatiegeschenken", MKBCategorie.VERKOOPKOSTEN),
    ("representatie", MKBCategorie.VERKOOPKOSTEN),
    # Personeel
    ("loon", MKBCategorie.PERSONEELSKOSTEN),
    ("salaris", MKBCategorie.PERSONEELSKOSTEN),
    ("pensioen", MKBCategorie.PERSONEELSKOSTEN),
    ("personeel", MKBCategorie.PERSONEELSKOSTEN),
    # Huisvesting
    ("huur", MKBCategorie.HUISVESTINGSKOSTEN),
    ("gas water licht", MKBCategorie.HUISVESTINGSKOSTEN),
    ("energie", MKBCategorie.HUISVESTINGSKOSTEN),
    # Kostprijs
    ("inkoop", MKBCategorie.KOSTPRIJS_OMZET),
    ("klein materiaal", MKBCategorie.KOSTPRIJS_OMZET),
    ("prijsverschil", MKBCategorie.KOSTPRIJS_OMZET),
    # Privé
    ("prive", MKBCategorie.PRIVE),
    ("privegebruik", MKBCategorie.PRIVE),
    ("kapitaalmutaties", MKBCategorie.PRIVE),  # privé-onttrekking
    # Omzet specifiek (vóór btw zodat 'omzet btw verlegd' niet onder BTW valt)
    ("omzet btw verlegd", MKBCategorie.OMZET),
    ("omzet hoog", MKBCategorie.OMZET),
    ("omzet laag", MKBCategorie.OMZET),
    # BTW
    ("btw", MKBCategorie.BTW),
    ("omzetbelasting", MKBCategorie.BTW),
    # Debiteuren / Crediteuren
    ("debiteur", MKBCategorie.DEBITEUREN),
    ("crediteur", MKBCategorie.SCHULDEN_KORT),
    # Liquide
    ("bank", MKBCategorie.LIQUIDE_MIDDELEN),
    ("ing", MKBCategorie.LIQUIDE_MIDDELEN),
    ("nl44", MKBCategorie.LIQUIDE_MIDDELEN),
    ("spaar", MKBCategorie.LIQUIDE_MIDDELEN),
    ("kruispost", MKBCategorie.LIQUIDE_MIDDELEN),
    # Vaste activa
    ("inventaris", MKBCategorie.VASTE_ACTIVA),
    ("bedrijfsgebouw", MKBCategorie.VASTE_ACTIVA),
    # Afschrijvingen
    ("afschrijving", MKBCategorie.AFSCHRIJVINGEN),
    # Financieel
    ("rente", MKBCategorie.FINANCIEEL),
    # Verkoopkortingen tellen we als verkoopkosten (negatieve omzet kan ook)
    ("kortingen", MKBCategorie.OMZET),  # negatieve omzet, maar in OMZET-categorie
    ("betalingsverschil", MKBCategorie.OMZET),
    # Eigen vermogen (na privé-check)
    ("kapitaal", MKBCategorie.EIGEN_VERMOGEN),
    ("eigen vermogen", MKBCategorie.EIGEN_VERMOGEN),
    # Algemene kosten (catch-all bedrijfslast)
    ("vooruitbetaa", MKBCategorie.VLOTTENDE_ACTIVA),
    ("vooruitgefactureerd", MKBCategorie.SCHULDEN_KORT),
    ("toestelkrediet", MKBCategorie.VLOTTENDE_ACTIVA),
    # Omzet (laatst, na overige check)
    ("omzet", MKBCategorie.OMZET),
]


def categorize_mkb(mapped: MappedRecord) -> MKBCategorie:
    """Map MappedRecord → MKB-light categorie via RGSCategory + naam-heuristiek."""
    if mapped.rgs_code is None:
        return MKBCategorie.OVERIG

    naam = (mapped.rgs_code.naam or "").lower() + " " + (mapped.clean.raw.pakket_grootboeknaam or "").lower()

    # Specifieke naam-rules eerst
    for needle, cat in _NAME_RULES:
        if needle in naam:
            return cat

    # Fallback op RGS-categorie
    rgs_cat = mapped.rgs_code.categorie
    if rgs_cat == RGSCategory.WV_OPBRENGSTEN:
        return MKBCategorie.OMZET  # "overige opbrengsten" valt al hiervoor onder verkoop-rule
    if rgs_cat == RGSCategory.WV_KOSTPRIJS:
        return MKBCategorie.KOSTPRIJS_OMZET
    if rgs_cat == RGSCategory.WV_BEDRIJFSLASTEN:
        return MKBCategorie.ALGEMENE_KOSTEN  # default voor onbekende bedrijfslast
    if rgs_cat == RGSCategory.WV_FINANCIEEL:
        return MKBCategorie.FINANCIEEL
    if rgs_cat == RGSCategory.WV_BELASTING:
        return MKBCategorie.BELASTINGEN
    if rgs_cat == RGSCategory.BALANS_ACTIVA:
        return MKBCategorie.VLOTTENDE_ACTIVA  # default voor balans-activa zonder match
    if rgs_cat == RGSCategory.BALANS_PASSIVA_EV:
        return MKBCategorie.EIGEN_VERMOGEN
    if rgs_cat == RGSCategory.BALANS_PASSIVA_VV:
        return MKBCategorie.SCHULDEN_KORT
    return MKBCategorie.OVERIG


def categorize_all(mapped_list: list[MappedRecord]) -> list[tuple[MappedRecord, MKBCategorie]]:
    return [(m, categorize_mkb(m)) for m in mapped_list]
