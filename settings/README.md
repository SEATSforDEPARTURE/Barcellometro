# Settings

Tutti i config file-based versionati e locali vivono **solo** in `settings/`.
`app/settings/` non è più usato come source of truth.

## Source of truth e migrazione

- Il source of truth per i template versionati è questa directory: `settings/`.
- I path canonici da documentare negli env example e nella documentazione sono solo `settings/...`.
- Eventuali riferimenti legacy a `app/settings/...` esistono solo come compatibilità temporanea o come nota storica nel piano di refactor; non vanno usati per nuovi setup.

## File disponibili

### Template versionati (`*.example.json`)
- `settings/barcello_trigger.example.json`
- `settings/entitlements.example.json`
- `settings/aura_rules.example.json`
- `settings/aura_archetypes.example.json`
- `settings/aura_missions.example.json`

### Override locali runtime (`*.json`, non versionati)
- `settings/barcello_trigger.json`
- `settings/entitlements.json`
- `settings/aura_rules.json`
- `settings/aura_archetypes.json`
- `settings/aura_missions.json`

## Setup rapido

Copia i file example che vuoi personalizzare:

```bash
cp settings/entitlements.example.json settings/entitlements.json
cp settings/aura_rules.example.json settings/aura_rules.json
cp settings/aura_archetypes.example.json settings/aura_archetypes.json
cp settings/aura_missions.example.json settings/aura_missions.json
cp settings/barcello_trigger.example.json settings/barcello_trigger.json
```

## Note operative

- `ENTITLEMENTS_CONFIG_PATH` deve puntare a `settings/entitlements.json` se vuoi usare override locali.
- I servizi Aura e Trigger leggono i runtime file in `settings/*.json` e, quando previsto, fanno fallback automatico al corrispondente `settings/*.example.json`.
- Per evitare path duplicati nel codice Python, i riferimenti centralizzati stanno in `app/core/config_paths.py`.
- In questa fase di preparazione al refactor strutturale non vanno spostati feature folders, moduli Python o comandi: si consolidano solo documentazione, template e path settings.
