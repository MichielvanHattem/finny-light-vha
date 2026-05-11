# finny-app — versie-historie

## 0.1.0-alpha — 10 mei 2026 (Fase A)

**Doel:** YoungTech MCP-only vertical slice, JvT-proof basis.

**Architectuur-besluit (10 mei 2026):** koers-correctie na ChatGPT-sparring. Eén codebase, één finny_core (submodule), adapter-pluggables, profielen als capability contracts. Vervangt eerder voornemen voor aparte `finny-vha` en `finny-v9-vha` repos.

### Geïmplementeerd
- Repo-structuur (A1)
- finny_core link via Path-resolver (zustermap of submodule) (A2)
- Profielschema met capability contract (A3) — niet in secrets, in versiebeheer
- Source loader met fail-fast validatie (A4)
- SourceAdapter ABC + MCP-adapter (A5)
- Refusal-test historische vraag (A6)
- Streamlit UI minimaal (A7)
- Smoke-test (A8)

### Bewust NIET in deze versie
- PDF-adapter (Fase C)
- CSV-adapter (Fase C)
- XAF-adapter (Fase C)
- Multi-source orchestratie (Fase C)
- Partnerportal (Fase D)
- Multi-tenant (later)

### Bekende beperkingen
- finny_core submodule-koppeling moet nog geconfigureerd worden door DGA bij eerste push naar GitHub
- Logging in App Insights nog niet ingericht (lokale Streamlit-logs alleen)
- Cross-tenant leakage-test ontbreekt (geen multi-tenant in fase A)
