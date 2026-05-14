"""Finny v3 - Data Quality Rapport (vervangt v0.1.0a1).

B2C: gebruiker upload CSV/PDF/RGS via UI. Finny constateert, repareert niet.
Conform Data Quality Protocol Finny B2C v1.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

import streamlit as st


def parse_nl_decimal(raw):
    s = (raw or "").strip().replace(" ", "")
    if not s:
        return Decimal("0")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def parse_nl_date(raw):
    try:
        return datetime.strptime(raw.strip(), "%d-%m-%Y").date()
    except (ValueError, AttributeError):
        return None


def load_rgs_codes_from_bytes(data):
    codes = set()
    text = data.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        c = (row.get("gl_code") or row.get("GLAccountCodeDescription") or "").strip()
        if c:
            codes.add(c)
    return codes


def read_csv_mutations(uploaded_files, fiscal_year):
    rows = []
    for uf in uploaded_files:
        text = uf.getvalue().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for row in reader:
            d = parse_nl_date(row.get("EntryDate", ""))
            if d is None or d.year != fiscal_year:
                continue
            rows.append({
                "amount": parse_nl_decimal(row.get("AmountDC", "0")),
                "gl": (row.get("GLAccountCodeDescription") or "").strip(),
            })
    return rows


def check_year_zero(rows, fy, is_closed):
    total = sum((r["amount"] for r in rows), Decimal("0"))
    n = len(rows)
    if not is_closed:
        return {"rule": "J-001", "name": "Boekjaar saldering", "status": "INFO", "year": fy,
                "summary": f"Jaar {fy} nog niet afgesloten ({n} mutaties, saldo EUR {total:,.2f})."}
    if abs(total) <= Decimal("1.00"):
        return {"rule": "J-001", "name": "Gesloten boekjaar op EUR 0", "status": "OK", "year": fy,
                "summary": f"Boekjaar {fy} saldeert correct op EUR 0 ({n} mutaties, totaal EUR {total:,.2f})."}
    return {"rule": "J-001", "name": "Gesloten boekjaar op EUR 0", "status": "ERROR", "year": fy,
            "summary": f"Boekjaar {fy} saldeert NIET op EUR 0 - delta EUR {total:,.2f} over {n} mutaties.",
            "recommendation": "Bespreek met je accountant. Debit moet credit zijn."}


def check_debit_credit(rows, fy):
    debit = sum((r["amount"] for r in rows if r["amount"] > 0), Decimal("0"))
    credit = sum((-r["amount"] for r in rows if r["amount"] < 0), Decimal("0"))
    delta = debit - credit
    if abs(delta) <= Decimal("0.01"):
        return {"rule": "J-004", "name": "Debit = Credit", "status": "OK", "year": fy,
                "summary": f"Debit EUR {debit:,.2f} approx Credit EUR {credit:,.2f}."}
    return {"rule": "J-004", "name": "Debit = Credit", "status": "ERROR", "year": fy,
            "summary": f"Onbalans: delta EUR {delta:,.2f}.",
            "recommendation": "Onbalans wijst op ontbrekende of dubbele boekingen."}


def check_unmapped(rows, fy, rgs_codes):
    unmapped = defaultdict(int)
    codes = set()
    for r in rows:
        if r["gl"]:
            codes.add(r["gl"])
            if r["gl"] not in rgs_codes:
                unmapped[r["gl"]] += 1
    if not codes:
        return {"rule": "J-003", "name": "RGS-mapping", "status": "INFO", "year": fy,
                "summary": "Geen GL-codes gevonden."}
    cov = (len(codes) - len(unmapped)) / len(codes) * 100
    if not unmapped:
        return {"rule": "J-003", "name": "RGS-mapping volledig", "status": "OK", "year": fy,
                "summary": f"Alle {len(codes)} GL-codes gemapt (100%)."}
    status = "WARNING" if cov >= 85 else "ERROR"
    return {"rule": "J-003", "name": "RGS-mapping", "status": status, "year": fy,
            "summary": f"Mapping {cov:.1f}% - {len(unmapped)} van {len(codes)} ontbreekt.",
            "details": dict(unmapped),
            "recommendation": "Vraag accountant om ontbrekende RGS-toewijzingen."}


st.set_page_config(page_title="Finny v3 DQ", layout="wide")
st.title("Finny v3 - Data Quality Rapport")
st.caption("Finny constateert data-kwaliteit. Repareert niet, reproduceert geen jaarrekening-cijfers (= accountant). Conform Data Quality Protocol Finny B2C v1.")

with st.sidebar:
    st.header("1) Upload je data")
    rgs_file = st.file_uploader("RGS-mapping (CSV semicolon)", type=["csv"])
    csv_files = st.file_uploader("Boekjaar-mutaties (Exact-CSV, meerdere)", type=["csv"], accept_multiple_files=True)
    st.divider()
    st.header("2) Welke jaren?")
    closed = st.multiselect("Gesloten boekjaren", list(range(2018, 2027)), default=[2022, 2023, 2024])
    open_y = st.multiselect("Lopende boekjaren", list(range(2024, 2028)), default=[2025, 2026])
    st.divider()
    st.markdown("**Privacy:** upload alleen in deze sessie, niets opgeslagen.")

if not rgs_file or not csv_files:
    st.info("Upload eerst je RGS-mapping en mutaties-CSV's om Finny te starten.")
    st.markdown("""
### Wat Finny v3 doet (en niet doet)

**Wel:** constateert of gesloten boekjaar saldeert op EUR 0, toont mapping-coverage GL-codes naar RGS, signaleert debit/credit-onbalans, wijst ontbrekende RGS-toewijzingen aan.

**Niet:** reproduceert geen jaarrekening-cijfers (= accountant), maakt geen correctieboekingen, geeft geen fiscaal advies.

Finny is een data-kwaliteits-spiegel voor je boekhouding.
    """)
    st.stop()

rgs_codes = load_rgs_codes_from_bytes(rgs_file.getvalue())
st.success(f"RGS-mapping geladen: {len(rgs_codes)} GL-codes")

results = []
for year in sorted(set(closed + open_y)):
    rows = read_csv_mutations(csv_files, year)
    if not rows:
        continue
    results.append(check_year_zero(rows, year, year in closed))
    if year in closed:
        results.append(check_debit_credit(rows, year))
    results.append(check_unmapped(rows, year, rgs_codes))

icons = {"OK": "OK", "WARNING": "WARN", "ERROR": "ERR", "INFO": "INFO"}
years = sorted({r["year"] for r in results})
tabs = st.tabs(["Samenvatting"] + [f"Jaar {y}" for y in years])

with tabs[0]:
    summary = []
    for y in years:
        yr = [r for r in results if r["year"] == y]
        ok = sum(1 for r in yr if r["status"] == "OK")
        wn = sum(1 for r in yr if r["status"] == "WARNING")
        er = sum(1 for r in yr if r["status"] == "ERROR")
        overall = "OK" if er == 0 and wn == 0 else ("WARN" if er == 0 else "ERR")
        summary.append({"Jaar": y, "Overall": overall, "OK": ok, "Warn": wn, "Error": er})
    st.dataframe(summary, use_container_width=True, hide_index=True)

for i, y in enumerate(years, start=1):
    with tabs[i]:
        st.subheader(f"Boekjaar {y}")
        for r in [x for x in results if x["year"] == y]:
            with st.expander(f"[{icons[r['status']]}] {r['rule']} - {r['name']}",
                             expanded=r["status"] in ("WARNING", "ERROR")):
                st.markdown(f"**Status:** {r['status']}")
                st.markdown(f"**Bevinding:** {r['summary']}")
                if r.get("recommendation"):
                    st.info(f"**Aanbeveling:** {r['recommendation']}")
                if r.get("details"):
                    with st.expander("Details: welke GL-codes ontbreken"):
                        st.json(r["details"])

st.divider()
st.caption(f"Finny v3 DQ Build - RGS v20251201 ({len(rgs_codes)} codes). Conform DQ Protocol v1. 14-mei-2026.")
