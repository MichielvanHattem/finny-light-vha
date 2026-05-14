# Finny v3 - Data Quality Build

Vervangt v0.1.0a1 op `finny-light-vha.streamlit.app`.

Doel: Finny constateert data-kwaliteit (RGS-mapping, gesloten-boekjaar-saldering, double-entry) en signaleert. Repareert NIET. Reproduceert geen jaarrekening-cijfers (= accountant's werk).

## Wat dit toont
- Meta-check J-001: gesloten boekjaar saldeert op EUR 0
- Meta-check J-003: RGS-mapping-coverage per jaar
- Meta-check J-004: Debit = Credit (double-entry)

## B2C-flow
Gebruiker upload via UI:
1. RGS-mapping CSV (semicolon-separated)
2. Boekjaar-mutaties CSV (Exact-export NL-format)
3. Kies welke jaren gesloten zijn / nog lopen

Finny geeft Data Quality Rapport per jaar. Geen data wordt opgeslagen.

Conform Data Quality Protocol Finny B2C v1.
