# Entitlements locali

`app/settings/entitlements.example.json` è il template versionato nel repository.
Il file locale `app/settings/entitlements.json` non è tracciato da Git.
Per creare la tua copia locale esegui:
`cp app/settings/entitlements.example.json app/settings/entitlements.json`
Compila localmente i campi `mod.role_ids` e `entitlements.profile_map.role_to_profile`.
Personalizza eventuali policy in `entitlements.policies` secondo il tuo ambiente.
Se il file locale manca, il servizio usa i default senza applicare override.

## Config Aura (rules/archetypes/missions)
- `app/settings/aura_rules.example.json`: punteggi per reason code Aura (override in `app/settings/aura_rules.json`).
- `app/settings/aura_archetypes.example.json`: label/emoji/descrizioni/consigli archetipi (override in `app/settings/aura_archetypes.json`).
- `app/settings/aura_missions.example.json`: catalogo missioni giornaliere (override in `app/settings/aura_missions.json`).
