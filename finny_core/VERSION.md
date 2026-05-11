# finny_core — Versionering

**Huidige versie:** 7.2.0 (9 mei 2026 middag — D-06 + D-07 + ChatGPT-feedback + PDF-cross-check + D-08 skeleton)

## Stamboom Finny (alle generaties)

| Generatie | Periode | Stack | Status |
|---|---|---|---|
| v1.x | mei 2025 | Node + Express + WordPress JWT | historisch |
| v2.x | mei 2025 | "Secure Edition" claim / Finny Lite werkelijkheid | historisch |
| v3.x | mei 2025 | Express + SharePoint + parsers (v3.6 → v3.9) | historisch |
| v4.x | jun-nov 2025 | B2C + Multi-tenant + Finnymini-routing | historisch |
| v5.x | jun-aug 2025 | Azure AI Search + JvT (v5.0 → v5.1) | **GEPARKEERD** per koerswijziging 8 mei |
| v6.x | apr 2026 | Streamlit `finny-vha.streamlit.app` (commit e9b6261) | **GEPARKEERD** per koerswijziging 8 mei |
| **v7.x** | **mei 2026** | **`finny_core` Python-package (deze repo)** | **ACTIEF** |
| v8.x | toekomst | Streamlit-Light wrapper boven finny_core | gepland |

## Roadmap finny_core (v7.x)

| Versie | Datum | Inhoud | Status |
|---|---|---|---|
| 7.0.0 | 9 mei 2026 nacht | Basis 9 lagen, sandwich-pattern, Q01 werkend, 6/6 tests | DONE |
| 7.0.1 | 9 mei 2026 middag | D-06 (geen-data-modus) + D-07 (source-quality) + Q03 BUG-fix, 12/12 tests | DONE |
| 7.0.2 | 9 mei 2026 middag | Versie-administratie vastgelegd | DONE |
| **7.1.0** | 9 mei 2026 middag | ChatGPT-feedback (HIGH_VERIFIED-split, opening_balance_verified, source_type, _is_real_expense, 6 tegenvoorbeeld-tests) | DONE |
| **7.2.0** | **9 mei 2026 middag** | **PDF-jaarrekening-adapter + cross_check_with_pdf → Q04/Q09 PARTIAL → ANSWERED HIGH_VERIFIED** | **DONE** |
| 7.3.0 | week 2 | MCP-koppeling (e-Boekhouden via Zapier) → live-data-bron | gepland |
| 7.4.0 | week 2-3 | Nieuwe intent-types (nettowinst, personeelskosten, autokosten, etc.): nettowinst, personeelskosten, autokosten, solvabiliteit, werkkapitaal, kasstroom, privé, btw-balans, investeringen | gepland |
| 8.0.0 | week 4+ | Streamlit-Light wrapper boven finny_core (gebruiker-zichtbare release) | gepland |

## SemVer-discipline

- **MAJOR (X.0.0):** breekende architectuurwijziging of generatie-overgang (bv. nieuwe stack-laag boven finny_core)
- **MINOR (x.Y.0):** nieuwe feature, achterwaarts compatibel (bv. nieuwe intent-type, nieuwe bron-adapter)
- **PATCH (x.y.Z):** bugfix of documentatie zonder API-wijziging

Versie bijhouden op:
- `pyproject.toml` (canonical)
- Deze VERSION.md (changelog)
- STATUS.md (huidige stand-overzicht)

## Detail-changelog v7.x sessie 9 mei middag

| Sub-versie | Inhoud |
|---|---|
| 7.0.0 | basis 9 lagen, sandwich-pattern, Q01 (nacht) |
| 7.0.1 | D-06 + D-07 + Q03 BUG-fix v1 |
| 7.0.2 | versie-administratie vastgelegd |
| 7.1.0 | ChatGPT-feedback (HIGH-split, opening_balance_verified, _is_real_expense, 6 tegenvoorbeeld-tests) |
| 7.1.1 | D-08 skeleton (QuestionComplexityTier, AnswerExpectation, INTENT_TIER_MAP) |
| **7.2.0** | **PDF-jaarrekening-adapter + cross_check_with_pdf — Q04/Q09 → ANSWERED HIGH_VERIFIED** |
| 7.3.0 | MCP-koppeling (gepland — zie ROADMAP_V73_MCP.md) |
| 7.4.0 | nieuwe intent-types (nettowinst, personeelskosten, autokosten, etc.) |
| 8.0.0 | dialoog-systeem (ConversationContext + LearningLog) — zie ROADMAP_V8.md |

## Tests-stand v7.2.0

**21/21 groen** (15 baseline + D-06/D-07 + 6 ChatGPT-tegenvoorbeelden + 3 PDF-cross-check)

## Werkende vragen v7.2.0

| Vraag | Mode | Cijfer | Confidence |
|---|---|---|---|
| Q01 omzet 2024 | ANSWERED | €81.540,85 (CSV) | HIGH_SINGLE_SOURCE |
| Q03 totale kosten 2024 | PARTIAL | €7.974,55 (na _is_real_expense) | MEDIUM |
| Q04 EV einde 2024 zonder PDF | PARTIAL | €79.085,42 (CSV-cumul, structureel fout) | MEDIUM |
| **Q04 EV einde 2024 MET PDF** | **ANSWERED** | **€27.716** (PDF-anker) | **HIGH_VERIFIED** |
| Q09 liquide einde 2024 zonder PDF | PARTIAL | €-9.760 (negatief, fysiek onmogelijk) | LOW |
| **Q09 liquide einde 2024 MET PDF** | **ANSWERED** | **€24.417** (PDF-anker) | **HIGH_VERIFIED** |
| omzet 2099 | REFUSED | (geen cijfer) | NONE |
