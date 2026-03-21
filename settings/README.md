# Settings

Tutti i config file-based versionati e locali vivono in `settings/`.

## Source of truth

- Il source of truth per i template versionati è questa directory: `settings/`.
- I path canonici da documentare negli env example e nella documentazione sono solo `settings/...`.
- Eventuali riferimenti a `app/settings/...` restano solo come compatibilità legacy intenzionale; non vanno usati per nuovi setup.

## File disponibili

### Template versionati (`*.example.json`)
- `settings/barcello_trigger.example.json`
- `settings/entitlements.example.json`
- `settings/greetings_trigger.example.json`
- `settings/aura_rules.example.json`
- `settings/aura_archetypes.example.json`
- `settings/aura_missions.example.json`

### Override locali runtime (`*.json`, non versionati)
- `settings/barcello_trigger.json`
- `settings/entitlements.json`
- `settings/greetings_trigger.json`
- `settings/aura_rules.json`
- `settings/aura_archetypes.json`
- `settings/aura_missions.json`

## Setup rapido

Copia i file example che vuoi personalizzare:

```bash
cp settings/entitlements.example.json settings/entitlements.json
cp settings/greetings_trigger.example.json settings/greetings_trigger.json
cp settings/aura_rules.example.json settings/aura_rules.json
cp settings/aura_archetypes.example.json settings/aura_archetypes.json
cp settings/aura_missions.example.json settings/aura_missions.json
cp settings/barcello_trigger.example.json settings/barcello_trigger.json
```

## Note operative

- `ENTITLEMENTS_CONFIG_PATH` deve puntare a `settings/entitlements.json` se vuoi usare override locali.
- I servizi Aura, Trigger e Greetings leggono i runtime file in `settings/*.json` e, quando previsto, fanno fallback automatico al corrispondente `settings/*.example.json`.
- Per evitare path duplicati nel codice Python, i riferimenti centralizzati stanno in `app/core/config_paths.py`.
- Gli override locali non devono reintrodurre wording legacy nei footer o nei template: `Dati elaborati` + ` in loco` ed `e fallback` + ` locale` sono aboliti in tutto il progetto.
- Se un file runtime come `settings/barcello_trigger.json` contiene campi come `footer`, `fallback_footer` o simili, per output non-AI non va salvata alcuna frase tecnica finale equivalente; per output AI si usa solo `Dati elaborati con ...` quando esistono davvero contributor/provider/model da dichiarare.
