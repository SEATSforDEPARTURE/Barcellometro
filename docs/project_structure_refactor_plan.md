# Project structure refactor plan

## Stato finale implementato

La struttura canonica del progetto è ora la seguente:

```text
settings/
app/
  services/
  renderers/
  utils/
  plugins/
    commands_modular/
```

## Regole architetturali

- `settings/` resta l'unica root per i file di configurazione versionati.
- I template config versionati ufficialmente ammessi in `settings/` sono:
  - `settings/barcello_trigger.example.json`
  - `settings/entitlements.example.json`
  - `settings/greetings_trigger.example.json`
  - `settings/aura_rules.example.json`
  - `settings/aura_archetypes.example.json`
  - `settings/aura_missions.example.json`
- `app/services/` è la root canonica per logica applicativa, business logic e integrazioni infrastructure.
- `app/renderers/` contiene tutti i renderer Discord/embed/output.
- `app/utils/` è riservata a helper puri/stateless e può anche restare vuota.
- `app/plugins/commands_modular/` contiene tutti i comandi slash modulari.
- `app/features/` è legacy e non deve più esistere né essere reintrodotta.

## Migrazione completata da `app/features`

### Activity
- `app/features/activity/services/activity_insights_service.py` → `app/services/activity_insights.py`
- `app/features/activity/services/activity_report_service.py` → `app/services/daily_activity_report.py`
- `app/features/activity/services/activity_sorting_service.py` → `app/services/daily_activity_sorting.py`
- `app/features/activity/renderers/activity_dm_report_renderer.py` → `app/renderers/activity_dm_report_renderer.py`
- `app/features/activity/renderers/activity_report_renderer.py` → `app/renderers/activity_report_renderer.py`
- `app/features/activity/renderers/user_activity_report_renderer.py` → `app/renderers/user_activity_report_renderer.py`
- `app/features/activity/commands/attivita.py` → `app/plugins/commands_modular/attivita.py`

### Aura
- `app/features/aura/services/aura_service.py` → `app/services/aura.py`
- `app/features/aura/services/aura_archetype_reason_builder.py` → `app/services/aura_archetypes.py`
- `app/features/aura/renderers/aura_renderer.py` → `app/renderers/aura_renderer.py`
- `app/features/aura/commands/aura.py` → `app/plugins/commands_modular/aura.py`

### Barcello
- `app/features/barcello/services/barcello_service.py` → `app/services/barcello_service.py`
- `app/features/barcello/services/barcello_calibration_service.py` → `app/services/barcello_calibration_service.py`
- `app/features/barcello/services/barcello_window_defaults.py` → `app/services/barcello_window_defaults.py`
- `app/features/barcello/commands/barcello.py` → `app/plugins/commands_modular/barcello.py`

### Summary
- `app/features/summary/services/channel_summary_service.py` → `app/services/channel_summary_service.py`
- `app/features/summary/services/content_summary_service.py` → `app/services/content_summary_service.py`
- `app/features/summary/services/message_name_service.py` → `app/services/message_name_service.py`
- `app/features/summary/services/server_activity_report_service.py` → `app/services/server_activity_report_service.py`
- `app/features/summary/renderers/channel_summary.py` → `app/renderers/channel_summary.py`
- `app/features/summary/renderers/detail_embeds.py` → `app/renderers/detail_embeds.py`
- `app/features/summary/renderers/server_activity_report_renderer.py` → `app/renderers/server_activity_report_renderer.py`
- `app/features/summary/commands/resoconto.py` → `app/plugins/commands_modular/resoconto.py`
- `app/features/summary/commands/riassunto.py` → `app/plugins/commands_modular/riassunto.py`

### Triggers
- `app/features/triggers/services/triggers_service.py` → `app/services/triggers_service.py`
- `app/features/triggers/commands/triggers.py` → `app/plugins/commands_modular/triggers.py`

## Compat layer rimossi

I seguenti shim legacy sono stati assorbiti nel codice canonico o eliminati; non devono essere reintrodotti come semplici re-export da `app.features`:

- `app/services/activity_insights.py`
- `app/services/daily_activity_report.py`
- `app/services/daily_activity_sorting.py`
- `app/services/aura.py`
- `app/services/aura_archetypes.py`
- `app/services/aura_render.py` (bridge storico ormai rimosso verso il renderer canonico in `app/renderers/`)
- `app/plugins/commands_modular/attivita.py`

## Vincoli permanenti

- Nessun import runtime deve puntare a `app.features...`.
- Nessun test/layout validator deve richiedere la presenza di `app/features`.
- L'eventuale reintroduzione di `app/features/` deve fallire la validazione del layout.
