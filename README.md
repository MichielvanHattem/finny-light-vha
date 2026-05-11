# finny-app

**Eén Streamlit-codebase, één finny_core motor, adapters als pluggables, profielen als capability contracts.**

## Architectuur

Volgt de koers-correctie van 10 mei 2026 (zie `_shared-memory/` in OneDrive):

- `finny_core` = motor (één bron van waarheid, bron-onafhankelijk, levert `AnswerMode` + `SourceQuality`).
- `adapters/` = data-bron-pluggables. Elk los, optioneel, met uniform `SourceAdapter`-contract.
- `orchestrator/` = leest profiel, valideert capabilities, laadt enabled adapters, faalt hard bij inconsistentie.
- `profiles/` = capability contracts in versiebeheer (NIET in secrets).
- `app.py` = Streamlit UI, profielconfiguratie bepaalt welke adapters actief zijn.

## Profielen

| Profiel | Bronnen | Tier | Status |
|---|---|---|---|
| `youngtech_mcp_only` | MCP/REST e-Boekhouden | B2C zelfboeker | Fase A |
| `demo_mcp_only` | MCP/REST e-Boekhouden | demo | Fase A |
| `full_history` | MCP + CSV + PDF + XAF | B2B met historie | Fase C |
| `vha_legacy_full` | CSV + PDF + XAF (legacy) | DGA-validatie | Fase C |

## Capability contract

Profielen definiëren niet alleen welke adapters actief zijn, maar ook:
- `allowed_question_scopes` (welke vraagtypen beantwoord mogen worden)
- `historical_years_supported` (true/false)
- `requires_refusal_on_missing_history` (true/false)

Een vraag buiten capability → `REFUSED` met heldere uitleg, NIET `PARTIAL`.

## Fail-fast principe

Bij startup wordt het profiel gevalideerd:
- Adapters die niet geïnstalleerd zijn maar wel in het profiel staan → startup faalt.
- Capabilities die geen ondersteunende adapter hebben → startup faalt.
- Ontbrekende credentials voor een actieve adapter → startup faalt.

Tijdens runtime: vraag buiten profiel-scope → REFUSED met `missing_capability` + `reason`.

## finny_core

`finny_core` zit in deze repo als git submodule uit een private core-repo. Versie + commit hash worden in elk antwoord gelogd. Geen lokale kopie, geen divergerende waarheid.

```
git submodule add <core-repo-url> finny_core
git submodule update --init --recursive
```

Voor lokale ontwikkeling kan finny_core ook als zustermap staan (`../finny_core`); de `orchestrator/profile_loader.py` zoekt beide paden.

## Deployment-tiers

Optionele dependencies per tier:
```bash
pip install -e ".[mcp]"       # YoungTech: alleen MCP
pip install -e ".[full]"      # Full-history: MCP + PDF + CSV + XAF
```

PDF/CSV/XAF-libraries worden NIET geïnstalleerd voor MCP-only deployments → kleinere attack surface.

## Logging per antwoord

Elke run logt verplicht:
- `core_version` + `core_commit`
- `app_version`
- `profile_id`
- `enabled_sources`
- `adapter_versions`
- `answer_mode` (ANSWERED/PARTIAL/REFUSED)
- `source_quality`
- `retrieved_sources`

Voor JvT-review: "deze run gebruikte finny_core 7.2.0, profiel youngtech_mcp_only, adapter mcp_eboekhouden v1.0.3, en gaf REFUSED omdat historische broncapaciteit ontbrak."

## Status

- Fase A (YoungTech MCP-only vertical slice): IN UITVOERING — 10 mei 2026
- Fase B (stabilisatie): TODO
- Fase C (Full-history adapters): TODO
- Fase D (release-hardening): TODO

Zie `VERSION.md` voor changelog.
