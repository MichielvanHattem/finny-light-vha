# finny_core

Duidingslaag tussen administratie-data en LLM-antwoord. Sandwich-pattern: **Python rekent, LLM legt uit** (lesson #68).

## Doel
- 95% deterministische correctheid op de SchilderwerkEZ + VHA testset
- Importeerbaar in JvT-Azure én Streamlit-Light
- Reproduceerbaar via `pytest`

## Status
v0 in opbouw — zie DECISION_LOG.md voor architectuurkeuzes.

## Architectuur-lagen
1. Bron-adapter (MCP/CSV/PDF)
2. Normalisatie (cleaning, datatypes)
3. RGS-mapping (pakket-code → RGS 3.5) — 100%-eis, geen fallback
4. Synoniemen-laag (klanttaal → categorie)
5. Vraag-classificatie + klantprofiel
6. Berekening-engine (deterministisch Python — KERN)
7. LLM-uitleg (template-substitution, geen herrekening mogelijk)
8. Validatie (cross-check tegen laag 6)
9. Output (gestructureerd antwoord met audit-trail)

## Run
```
pip install -e .
pytest
python -m finny_core "Wat was de omzet 2024?"
```
