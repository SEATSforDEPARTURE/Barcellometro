# Project structure refactor plan

> Nota: il refactor è stato implementato e il source of truth attuale è `settings/`. I riferimenti a `app/settings/` rimasti in questo documento descrivono lo stato legacy analizzato prima della migrazione.

## Scope and intent

Questo documento è un audit concreto dell'attuale struttura del repository e propone un refactor **solo strutturale** per:

- centralizzare tutte le configurazioni file-based sotto la root `settings/`
- eliminare la duplicazione tra `settings/` e `app/settings/`
- ridurre la dispersione tra `app/services/`, `app/renderers/` e `app/utils/`
- preparare una struttura più coerente per dominio/feature
- preservare il comportamento attuale durante la migrazione tramite compatibility shims temporanei

---

## 1) Audit completo dei file che leggono/scrivono config JSON o hanno path hardcoded verso config

### 1.1 Config file presenti oggi

#### Root `settings/`

| Path | Tipo attuale | Note |
|---|---|---|
| `settings/barcello_trigger.example.json` | template versionato | unico file config già centralizzato nella root |

#### `app/settings/`

| Path | Tipo attuale | Note |
|---|---|---|
| `app/settings/entitlements.example.json` | template versionato | duplicazione concettuale con l'obiettivo di centralizzare in `settings/` |
| `app/settings/aura_rules.example.json` | template versionato | idem |
| `app/settings/aura_archetypes.example.json` | template versionato | idem |
| `app/settings/aura_missions.example.json` | template versionato | idem |
| `app/settings/README.entitlements.md` | documentazione | documenta runtime files locali dentro `app/settings/` |

### 1.2 Runtime local JSON attesi dal codice oggi

Questi file non sono versionati ma sono implicitamente supportati o documentati:

| Runtime local JSON | Dove viene atteso | Meccanismo attuale |
|---|---|---|
| `settings/barcello_trigger.json` | Barcello / Triggers / Aura commands | letto direttamente; fallback automatico a `settings/barcello_trigger.example.json` |
| `app/settings/entitlements.json` | `ConfigOverridesService` | default path hardcoded + override via env `ENTITLEMENTS_CONFIG_PATH` |
| `app/settings/aura_rules.json` | Aura scoring | letto direttamente; fallback a `.example.json` |
| `app/settings/aura_archetypes.json` | Aura render | letto direttamente; fallback a `.example.json` |
| `app/settings/aura_missions.json` | Aura scoring/render | letto direttamente; fallback a `.example.json` |

### 1.3 File applicativi che leggono config JSON o hanno path hardcoded verso config

| File | Tipo di accesso | Riferimenti espliciti da segnalare | Osservazioni |
|---|---|---|---|
| `app/services/config_file_loader.py` | lettura JSON generica | `settings/barcello_trigger.json`, `.example.json` | contiene il fallback speciale hardcoded solo per Barcello; è il punto naturale da spostare in un package `app/config/` |
| `app/services/config_overrides.py` | lettura config + path default + env override | `app/settings/entitlements.json` | centralizza il caricamento di `entitlements.json`, ma punta ancora sotto `app/settings/` |
| `app/services/aura.py` | lettura config | `app/settings/aura_rules.json`, `app/settings/aura_rules.example.json`, `app/settings/aura_missions.json`, `app/settings/aura_missions.example.json` | hardcoded multipli di config Aura |
| `app/services/aura_render.py` | lettura config | `app/settings/aura_archetypes.json`, `app/settings/aura_archetypes.example.json`, `app/settings/aura_missions.json`, `app/settings/aura_missions.example.json` | duplicazione di lookup Aura |
| `app/services/triggers.py` | lettura config | `settings/barcello_trigger.json` | path hardcoded di trigger config |
| `app/plugins/commands_modular/triggers.py` | lettura config | `settings/barcello_trigger.json` | duplicazione del path del servizio |
| `app/plugins/commands_modular/barcello.py` | lettura config | `settings/barcello_trigger.json` | duplicazione del path del servizio |
| `app/plugins/commands_modular/aura.py` | lettura config | `settings/barcello_trigger.json` | il comando Aura dipende da un config Barcello per la finestra default |

### 1.4 File di supporto, documentazione, env e test con path hardcoded verso config

| File | Categoria | Riferimenti espliciti da segnalare | Impatto migrazione |
|---|---|---|---|
| `app/settings/README.entitlements.md` | doc | `app/settings/...`, `.example.json`, runtime `.json` locali | va spostato/riscritto in `settings/README.md` |
| `example.main.env` | env example | `ENTITLEMENTS_CONFIG_PATH=app/settings/entitlements.json` | da aggiornare a `settings/entitlements.json` |
| `example.worker1.env` | env example | `ENTITLEMENTS_CONFIG_PATH=app/settings/entitlements.json` | idem |
| `example.worker2.env` | env example | `ENTITLEMENTS_CONFIG_PATH=app/settings/entitlements.json` | idem |
| `tests/test_config_file_loader.py` | test | `settings/barcello_trigger.json`, `settings/barcello_trigger.example.json` | resta vicino al target finale; va aggiornato solo se cambia modulo loader |
| `tests/test_config_overrides.py` | test | `entitlements.json` locale temporaneo | da riallineare al nuovo modulo `app.config.*` |
| `tests/test_entitlements_example.py` | test | `app/settings/entitlements.example.json` | da puntare a `settings/entitlements.example.json` |
| `tests/test_aura.py` | test | match su `aura_rules.json` | da aggiornare se cambia convenzione path Aura |
| `tests/test_aura_render.py` | test | match su `aura_archetypes.json`, `aura_archetypes.example.json`, `aura_missions.json`, `aura_missions.example.json` | da riallineare ai nuovi path in `settings/` |
| `tests/test_pii_and_triggers.py` | test | `barcello_trigger.json` runtime locale | potenzialmente invariato come nome file, ma da riallineare al nuovo modulo/import |

### 1.5 Riferimenti richiesti, esplicitati separatamente

#### Riferimenti a `app/settings/...`

- `app/services/config_overrides.py`
- `app/services/aura.py`
- `app/services/aura_render.py`
- `app/settings/README.entitlements.md`
- `example.main.env`
- `example.worker1.env`
- `example.worker2.env`
- `tests/test_entitlements_example.py`

#### Riferimenti a `settings/...`

- `app/services/config_file_loader.py`
- `app/services/triggers.py`
- `app/plugins/commands_modular/triggers.py`
- `app/plugins/commands_modular/barcello.py`
- `app/plugins/commands_modular/aura.py`
- `tests/test_config_file_loader.py`

#### Riferimenti a `.example.json`

- `app/services/config_file_loader.py`
- `app/services/aura.py`
- `app/services/aura_render.py`
- `app/settings/README.entitlements.md`
- `tests/test_config_file_loader.py`
- `tests/test_entitlements_example.py`
- `tests/test_aura_render.py`

#### Riferimenti a `.json` runtime locali

- `settings/barcello_trigger.json`
- `app/settings/entitlements.json`
- `app/settings/aura_rules.json`
- `app/settings/aura_archetypes.json`
- `app/settings/aura_missions.json`
- test temporanei in `tests/test_config_overrides.py`, `tests/test_pii_and_triggers.py`, `tests/test_config_file_loader.py`

### 1.6 Conclusione audit config

Lo stato attuale usa **due radici di configurazione distinte**:

- `settings/` per Barcello trigger
- `app/settings/` per entitlements + Aura

Questa doppia convenzione è la principale fonte di attrito. Il refactor dovrebbe convergere su **una sola directory versionata: `settings/`**, mantenendo i nomi file attuali per minimizzare il rischio.

---

## 2) File in `app/renderers/` e `app/utils/` che in realtà appartengono a una feature specifica

### 2.1 `app/renderers/`: classificazione per feature

| File attuale | Feature reale | Evidenza pratica | Proposta |
|---|---|---|---|
| `app/renderers/activity_daily_report_renderer.py` | attività / report giornaliero | importato solo da `app/services/daily_activity_report.py` e dai test dedicati | spostare dentro feature `activity` |
| `app/renderers/activity_dm_renderer.py` | attività / report utente DM | importato solo da `app/plugins/commands_modular/attivita.py` e test attività | spostare dentro feature `activity` |
| `app/renderers/user_activity_renderer.py` | attività / user activity | importato solo da `app/plugins/commands_modular/attivita.py` | spostare dentro feature `activity` |
| `app/renderers/channel_summary_renderer.py` | summary / resoconto / riassunto | importato da `app/services/channel_summary.py` e riusato da `activity_daily_report_renderer.py` per il `window_header` | spostare dentro feature `summary` |
| `app/renderers/daily_resoconto_renderer.py` | summary / daily resoconto | semanticamente summary-specific; non ha import diretti attuali e appare come renderer legacy/orfano | spostare dentro feature `summary` e trattare come legacy shim temporaneo |

### 2.2 `app/utils/`: file non veramente shared

| File attuale | Feature reale | Perché non è davvero shared | Proposta |
|---|---|---|---|
| `app/utils/summary_render.py` | riassunto / summary details | costruisce embed dei dettagli del riassunto; è importato solo da `commands_modular/riassunto.py` | spostare in `summary/renderers/` |
| `app/utils/summary_names.py` | channel summary / summary linking | risolve message ids e display names per il summary; è importato solo da `app/services/channel_summary.py` | spostare in `summary/services/` o `summary/support/` |
| `app/utils/trend_render.py` | dominio “trend/clima” usato da Barcello + Summary | non è un helper truly generic dell'intera app; è specifico dei report/clima | spostare in un namespace di dominio condiviso, non in `utils/` generica |
| `app/utils/discord_send.py` | attualmente soprattutto riassunto/report delivery | oggi è usato solo da `commands_modular/riassunto.py`; è cross-cutting ma orientato alla delivery di report embed | spostare in shared Discord infra (`app/shared/discord/`) |

### 2.3 `app/utils/`: file che restano shared/infrastructural

Questi non risultano feature-specific e possono vivere in uno spazio shared dedicato:

| File attuale | Natura | Proposta |
|---|---|---|
| `app/utils/command_embeds.py` | shared Discord response builder | `app/shared/discord/command_embeds.py` |
| `app/utils/report_embeds.py` | shared report presentation | `app/shared/discord/report_embeds.py` |
| `app/utils/component_notices.py` | shared component notice helper | `app/shared/discord/component_notices.py` |
| `app/utils/embed_limits.py` | shared embed chunking/limits | `app/shared/discord/embed_limits.py` |
| `app/utils/footer_pipeline.py` | shared footer finalization infra | `app/shared/discord/footer_pipeline.py` |
| `app/utils/pii.py` | shared safety/privacy helper | `app/shared/safety/pii.py` |

### 2.4 Riferimenti richiesti: import da `app.renderers`

Import applicativi attuali da segnalare esplicitamente:

- `app/services/daily_activity_report.py` → `app.renderers.activity_daily_report_renderer`
- `app/plugins/commands_modular/attivita.py` → `app.renderers.activity_dm_renderer`
- `app/plugins/commands_modular/attivita.py` → `app.renderers.user_activity_renderer`
- `app/services/channel_summary.py` → `app.renderers.channel_summary_renderer`
- `app/renderers/activity_daily_report_renderer.py` → `app.renderers.channel_summary_renderer`

Import testuali/test attuali da segnalare:

- `tests/test_activity_daily_report_renderer.py`
- `tests/test_activity_dm_renderer.py`
- `tests/test_activity_display_names.py`
- `tests/test_resoconto_channel_summary_regressions.py`

### 2.5 Riferimenti richiesti: import da `app.utils` con responsabilità non davvero shared

Questi import sono i candidati principali a uscire da `app.utils`:

| Import attuale | File che lo usa | Target consigliato |
|---|---|---|
| `from app.utils.summary_render import ...` | `app/plugins/commands_modular/riassunto.py` | `app.features.summary.renderers.detail_embeds` |
| `from app.utils.summary_names import ...` | `app/services/channel_summary.py` | `app.features.summary.services.message_names` |
| `from app.utils.trend_render import ...` | `app/plugins/commands_modular/barcello.py` | `app.domain.reporting.trend` |
| `from app.utils.trend_render import ...` | `app/renderers/channel_summary_renderer.py` | `app.domain.reporting.trend` |
| `from app.utils.trend_render import ...` | `app/renderers/daily_resoconto_renderer.py` | `app.domain.reporting.trend` |
| `from app.utils.discord_send import ...` | `app/plugins/commands_modular/riassunto.py` | `app.shared.discord.delivery` |

---

## 3) Proposta di target structure concreta, con mapping `from -> to`

## 3.1 Target structure proposta

```text
settings/
  README.md
  barcello_trigger.example.json
  entitlements.example.json
  aura_rules.example.json
  aura_archetypes.example.json
  aura_missions.example.json

app/
  config/
    __init__.py
    file_loader.py
    overrides.py
  shared/
    discord/
      __init__.py
      command_embeds.py
      report_embeds.py
      component_notices.py
      embed_limits.py
      footer_pipeline.py
      delivery.py
    safety/
      __init__.py
      pii.py
  domain/
    reporting/
      __init__.py
      trend.py
  features/
    activity/
      __init__.py
      commands/
        attivita.py
      renderers/
        activity_dm.py
        daily_report.py
        user_activity.py
      services/
        activity_insights.py
        daily_activity_report.py
        daily_activity_sorting.py
    aura/
      __init__.py
      commands/
        aura.py
      renderers/
        aura.py
      services/
        archetypes.py
        aura.py
    barcello/
      __init__.py
      commands/
        barcello.py
      services/
        barcello.py
        calibration.py
        window_defaults.py
    summary/
      __init__.py
      commands/
        resoconto.py
        riassunto.py
      renderers/
        channel_summary.py
        daily_resoconto.py
        detail_embeds.py
      services/
        channel_summary.py
        daily_resoconto.py
        message_names.py
        summary.py
    triggers/
      __init__.py
      commands/
        triggers.py
      services/
        triggers.py
```

### 3.2 Mapping config/doc files

| From | To | Note |
|---|---|---|
| `app/settings/entitlements.example.json` | `settings/entitlements.example.json` | elimina duplicazione e porta entitlements nella root settings |
| `app/settings/aura_rules.example.json` | `settings/aura_rules.example.json` | idem |
| `app/settings/aura_archetypes.example.json` | `settings/aura_archetypes.example.json` | idem |
| `app/settings/aura_missions.example.json` | `settings/aura_missions.example.json` | idem |
| `app/settings/README.entitlements.md` | `settings/README.md` | README unico per tutti i config file-based |
| `settings/barcello_trigger.example.json` | `settings/barcello_trigger.example.json` | resta dov'è |

### 3.3 Mapping moduli config/infrastructure

| From | To | Motivazione |
|---|---|---|
| `app/services/config_file_loader.py` | `app/config/file_loader.py` | non è un service di business; è infrastructure/config |
| `app/services/config_overrides.py` | `app/config/overrides.py` | stesso motivo |
| `app/utils/command_embeds.py` | `app/shared/discord/command_embeds.py` | shared UI infra |
| `app/utils/report_embeds.py` | `app/shared/discord/report_embeds.py` | shared UI infra |
| `app/utils/component_notices.py` | `app/shared/discord/component_notices.py` | shared UI infra |
| `app/utils/embed_limits.py` | `app/shared/discord/embed_limits.py` | shared UI infra |
| `app/utils/footer_pipeline.py` | `app/shared/discord/footer_pipeline.py` | shared UI infra |
| `app/utils/discord_send.py` | `app/shared/discord/delivery.py` | delivery helper più chiaro e non in `utils/` |
| `app/utils/pii.py` | `app/shared/safety/pii.py` | helper trasversale di privacy/safety |
| `app/utils/trend_render.py` | `app/domain/reporting/trend.py` | helper di dominio, non util generica |

### 3.4 Mapping feature Activity

| From | To |
|---|---|
| `app/plugins/commands_modular/attivita.py` | `app/features/activity/commands/attivita.py` |
| `app/services/activity_insights.py` | `app/features/activity/services/activity_insights.py` |
| `app/services/daily_activity_report.py` | `app/features/activity/services/daily_activity_report.py` |
| `app/services/daily_activity_sorting.py` | `app/features/activity/services/daily_activity_sorting.py` |
| `app/renderers/activity_daily_report_renderer.py` | `app/features/activity/renderers/daily_report.py` |
| `app/renderers/activity_dm_renderer.py` | `app/features/activity/renderers/activity_dm.py` |
| `app/renderers/user_activity_renderer.py` | `app/features/activity/renderers/user_activity.py` |

### 3.5 Mapping feature Summary / Resoconto / Riassunto

| From | To |
|---|---|
| `app/plugins/commands_modular/resoconto.py` | `app/features/summary/commands/resoconto.py` |
| `app/plugins/commands_modular/riassunto.py` | `app/features/summary/commands/riassunto.py` |
| `app/services/channel_summary.py` | `app/features/summary/services/channel_summary.py` |
| `app/services/summary.py` | `app/features/summary/services/summary.py` |
| `app/services/daily_resoconto.py` | `app/features/summary/services/daily_resoconto.py` |
| `app/renderers/channel_summary_renderer.py` | `app/features/summary/renderers/channel_summary.py` |
| `app/renderers/daily_resoconto_renderer.py` | `app/features/summary/renderers/daily_resoconto.py` |
| `app/utils/summary_render.py` | `app/features/summary/renderers/detail_embeds.py` |
| `app/utils/summary_names.py` | `app/features/summary/services/message_names.py` |

### 3.6 Mapping feature Barcello

| From | To |
|---|---|
| `app/plugins/commands_modular/barcello.py` | `app/features/barcello/commands/barcello.py` |
| `app/services/barcello.py` | `app/features/barcello/services/barcello.py` |
| `app/services/barcello_calibration.py` | `app/features/barcello/services/calibration.py` |
| `app/services/barcello_window.py` | `app/features/barcello/services/window_defaults.py` |

### 3.7 Mapping feature Aura

| From | To |
|---|---|
| `app/plugins/commands_modular/aura.py` | `app/features/aura/commands/aura.py` |
| `app/services/aura.py` | `app/features/aura/services/aura.py` |
| `app/services/aura_render.py` | `app/features/aura/renderers/aura.py` |
| `app/services/aura_archetypes.py` | `app/features/aura/services/archetypes.py` |

### 3.8 Mapping feature Triggers

| From | To |
|---|---|
| `app/plugins/commands_modular/triggers.py` | `app/features/triggers/commands/triggers.py` |
| `app/services/triggers.py` | `app/features/triggers/services/triggers.py` |

### 3.9 Note importanti sul target

- **Non rinominerei i file JSON** (`barcello_trigger`, `entitlements`, `aura_rules`, `aura_archetypes`, `aura_missions`), cambierei solo la directory. Questo riduce il rischio.
- Il refactor di `daily_resoconto_renderer.py` va gestito come caso **legacy**: oggi non ha import diretti ma appartiene chiaramente al dominio Summary.
- Il refactor di `trend_render.py` non deve finire in una nuova `utils/` parallela: meglio un namespace di dominio (`app/domain/reporting/`).

---

## 4) Elenco degli import da aggiornare

Di seguito gli import concreti da toccare durante la migrazione.

### 4.1 Config package

| Import attuale | Nuovo import | File impattati |
|---|---|---|
| `from app.services.config_file_loader import load_json_file` | `from app.config.file_loader import load_json_file` | `app/services/triggers.py`, `app/plugins/commands_modular/triggers.py`, `app/plugins/commands_modular/barcello.py`, `app/plugins/commands_modular/aura.py`, `app/services/aura.py`, `app/services/aura_render.py`, `app/services/config_overrides.py`, `tests/test_config_file_loader.py` |
| `from app.services.config_overrides import ConfigOverridesService` | `from app.config.overrides import ConfigOverridesService` | `app/main.py`, `tests/test_config_overrides.py` |

### 4.2 Activity imports

| Import attuale | Nuovo import | File impattati |
|---|---|---|
| `from app.renderers.activity_daily_report_renderer import ...` | `from app.features.activity.renderers.daily_report import ...` | `app/services/daily_activity_report.py`, `tests/test_activity_daily_report_renderer.py` |
| `from app.renderers.activity_dm_renderer import ...` | `from app.features.activity.renderers.activity_dm import ...` | `app/plugins/commands_modular/attivita.py`, `tests/test_activity_dm_renderer.py`, `tests/test_activity_display_names.py` |
| `from app.renderers.user_activity_renderer import ...` | `from app.features.activity.renderers.user_activity import ...` | `app/plugins/commands_modular/attivita.py` |

### 4.3 Summary imports

| Import attuale | Nuovo import | File impattati |
|---|---|---|
| `from app.renderers.channel_summary_renderer import ...` | `from app.features.summary.renderers.channel_summary import ...` | `app/services/channel_summary.py`, `app/renderers/activity_daily_report_renderer.py` |
| `from app.utils.summary_render import ...` | `from app.features.summary.renderers.detail_embeds import ...` | `app/plugins/commands_modular/riassunto.py` |
| `from app.utils.summary_names import ...` | `from app.features.summary.services.message_names import ...` | `app/services/channel_summary.py` |

### 4.4 Domain/shared imports

| Import attuale | Nuovo import | File impattati |
|---|---|---|
| `from app.utils.trend_render import ...` | `from app.domain.reporting.trend import ...` | `app/plugins/commands_modular/barcello.py`, `app/renderers/channel_summary_renderer.py`, `app/renderers/daily_resoconto_renderer.py` |
| `from app.utils.discord_send import ...` | `from app.shared.discord.delivery import ...` | `app/plugins/commands_modular/riassunto.py` |
| `from app.utils.command_embeds import ...` | `from app.shared.discord.command_embeds import ...` | `app/plugins/commands.py`, tutti i moduli in `app/plugins/commands_modular/` che lo importano, `app/services/triggers.py`, `app/utils/component_notices.py` |
| `from app.utils.report_embeds import ...` | `from app.shared.discord.report_embeds import ...` | `app/plugins/commands_modular/resoconto.py`, `app/plugins/commands_modular/aura.py`, `app/plugins/commands_modular/attivita.py`, `app/plugins/commands_modular/barcello.py`, `app/plugins/commands_modular/riassunto.py`, `app/services/triggers.py` |
| `from app.utils.component_notices import ...` | `from app.shared.discord.component_notices import ...` | `app/plugins/commands_modular/barcello.py`, `app/services/campaign_content_service.py`, `app/services/inactive_members_moderation.py`, `app/services/daily_activity_report.py` |
| `from app.utils.embed_limits import ...` | `from app.shared.discord.embed_limits import ...` | `app/plugins/commands_modular/barcello.py`, `app/plugins/commands_modular/riassunto.py`, `app/services/aura_render.py`, `app/services/channel_summary.py`, `app/utils/discord_send.py`, `app/utils/summary_render.py`, `tests/test_aura_render.py`, `tests/test_footer_meta.py` |
| `from app.utils.footer_pipeline import ...` | `from app.shared.discord.footer_pipeline import ...` | `app/plugins/commands.py`, `app/utils/discord_send.py`, `tests/test_footer_meta.py` |
| `from app.utils.pii import ...` | `from app.shared.safety.pii import ...` | `app/plugins/discord_adapter.py`, `app/services/triggers.py`, `tests/test_pii_and_triggers.py` |

### 4.5 Nota sulla strategia import

Per ridurre il rischio, conviene aggiornare gli import in due fasi:

1. introdurre i nuovi moduli con re-export shim nei path vecchi;
2. aggiornare i consumer reali uno alla volta;
3. rimuovere gli shim solo in un secondo cleanup.

---

## 5) Elenco dei test da aggiornare

### 5.1 Test sicuramente da aggiornare per path config/module rename

| Test | Motivo |
|---|---|
| `tests/test_config_file_loader.py` | cambia il modulo del loader; verifica anche `settings/barcello_trigger.json` |
| `tests/test_config_overrides.py` | cambia il modulo `ConfigOverridesService` |
| `tests/test_entitlements_example.py` | oggi legge `app/settings/entitlements.example.json`; dovrà leggere `settings/entitlements.example.json` |
| `tests/test_aura.py` | monkeypatch/path matching su `aura_rules.json`; da riallineare ai nuovi path centralizzati |
| `tests/test_aura_render.py` | monkeypatch/path matching su `aura_archetypes*.json` e `aura_missions*.json`; da riallineare a `settings/` |
| `tests/test_pii_and_triggers.py` | cambia import di `pii` se viene spostato in `app/shared/safety/`; possibile aggiornamento anche del modulo triggers |

### 5.2 Test sicuramente da aggiornare per spostamento renderer/feature files

| Test | Motivo |
|---|---|
| `tests/test_activity_daily_report_renderer.py` | importa `app.renderers.activity_daily_report_renderer` |
| `tests/test_activity_dm_renderer.py` | importa `app.renderers.activity_dm_renderer` |
| `tests/test_activity_display_names.py` | importa `app.renderers.activity_dm_renderer` |
| `tests/test_resoconto_channel_summary_regressions.py` | legge il file sorgente `app/renderers/channel_summary_renderer.py` come testo |

### 5.3 Test/shared infra da aggiornare se vengono mossi i moduli `app.utils`

| Test | Motivo |
|---|---|
| `tests/test_footer_meta.py` | importa `app.utils.embed_limits` e `app.utils.footer_pipeline` |
| `tests/test_audio_notes_commands.py` | stubba esplicitamente `app.utils.command_embeds` in `sys.modules` |

### 5.4 Test potenzialmente da controllare anche se non cambiano subito

| Test | Perché va ricontrollato |
|---|---|
| `tests/test_import_smoke.py` | smoke test transitive import; utile dopo i move per intercettare path residuali |
| `tests/test_commands_namespace_refactor.py` | verifica file/namespace dei comandi in forma testuale; da rieseguire dopo lo spostamento dei command modules |

---

## 6) File legacy/duplicati che possono diventare compatibility shims temporanei

### 6.1 Shims Python raccomandati

| File legacy | Shim temporaneo consigliato |
|---|---|
| `app/services/config_file_loader.py` | re-export: `from app.config.file_loader import *` |
| `app/services/config_overrides.py` | re-export: `from app.config.overrides import *` |
| `app/renderers/activity_daily_report_renderer.py` | re-export dal nuovo modulo activity |
| `app/renderers/activity_dm_renderer.py` | re-export dal nuovo modulo activity |
| `app/renderers/user_activity_renderer.py` | re-export dal nuovo modulo activity |
| `app/renderers/channel_summary_renderer.py` | re-export dal nuovo modulo summary |
| `app/renderers/daily_resoconto_renderer.py` | re-export dal nuovo modulo summary |
| `app/utils/summary_render.py` | re-export dal nuovo modulo summary |
| `app/utils/summary_names.py` | re-export dal nuovo modulo summary |
| `app/utils/trend_render.py` | re-export dal nuovo modulo domain/reporting |
| `app/utils/discord_send.py` | re-export dal nuovo modulo shared/discord |
| `app/utils/command_embeds.py` | re-export dal nuovo modulo shared/discord |
| `app/utils/report_embeds.py` | re-export dal nuovo modulo shared/discord |
| `app/utils/component_notices.py` | re-export dal nuovo modulo shared/discord |
| `app/utils/embed_limits.py` | re-export dal nuovo modulo shared/discord |
| `app/utils/footer_pipeline.py` | re-export dal nuovo modulo shared/discord |
| `app/utils/pii.py` | re-export dal nuovo modulo shared/safety |

### 6.2 Duplicati config/documentazione da tenere solo come ponte breve

| Duplicato legacy | Compatibilità temporanea consigliata | Nota |
|---|---|---|
| `app/settings/entitlements.example.json` | copia/symlink temporaneo a `settings/entitlements.example.json` | da eliminare appena aggiornati test/docs |
| `app/settings/aura_rules.example.json` | copia/symlink temporaneo a `settings/aura_rules.example.json` | idem |
| `app/settings/aura_archetypes.example.json` | copia/symlink temporaneo a `settings/aura_archetypes.example.json` | idem |
| `app/settings/aura_missions.example.json` | copia/symlink temporaneo a `settings/aura_missions.example.json` | idem |
| `app/settings/README.entitlements.md` | stub minimale che rimanda a `settings/README.md` | meglio non mantenerlo a lungo |

### 6.3 Runtime compatibility temporanea per i local `.json`

Per una fase breve, il loader può supportare anche i path legacy:

- se viene chiesto `app/settings/entitlements.json`, leggere `settings/entitlements.json`
- se viene chiesto `app/settings/aura_rules.json`, leggere `settings/aura_rules.json`
- se viene chiesto `app/settings/aura_archetypes.json`, leggere `settings/aura_archetypes.json`
- se viene chiesto `app/settings/aura_missions.json`, leggere `settings/aura_missions.json`

Questo è utile solo per ridurre il rischio nei deploy intermedi. Va rimosso appena completata la migrazione.

---

## 7) Checklist di migrazione in step piccoli e sicuri

### Fase 0 — Baseline

- [ ] Congelare la semantica attuale con test verdi.
- [ ] Annotare i path config attuali supportati: `settings/barcello_trigger.json` e `app/settings/*.json`.
- [ ] Decidere se usare copie o symlink temporanei per i file example sotto `app/settings/`.

### Fase 1 — Centralizzazione config senza toccare feature folders

- [ ] Copiare/spostare tutti i `.example.json` di `app/settings/` in `settings/`.
- [ ] Creare `settings/README.md` con tutte le istruzioni operative oggi sparse in `app/settings/README.entitlements.md`.
- [ ] Aggiornare `example.main.env`, `example.worker1.env`, `example.worker2.env` a `ENTITLEMENTS_CONFIG_PATH=settings/entitlements.json`.
- [ ] Estendere il loader/config resolution per accettare temporaneamente sia `settings/...` sia `app/settings/...` per entitlements e Aura.
- [ ] Aggiornare i test che leggono direttamente gli example file.

### Fase 2 — Estrarre il package `app/config`

- [ ] Introdurre `app/config/file_loader.py` e `app/config/overrides.py`.
- [ ] Lasciare `app/services/config_file_loader.py` e `app/services/config_overrides.py` come shim di re-export.
- [ ] Aggiornare `app/main.py` e i consumer più semplici ai nuovi import.
- [ ] Rieseguire i test config-related.

### Fase 3 — Estrarre lo shared Discord infra

- [ ] Creare `app/shared/discord/`.
- [ ] Spostare `command_embeds`, `report_embeds`, `component_notices`, `embed_limits`, `footer_pipeline`, `discord_send`.
- [ ] Lasciare shim in `app/utils/`.
- [ ] Aggiornare progressivamente i consumer; iniziare da moduli con meno dipendenze.
- [ ] Aggiornare `tests/test_footer_meta.py` e `tests/test_audio_notes_commands.py`.

### Fase 4 — Estrarre lo shared safety/domain

- [ ] Creare `app/shared/safety/pii.py` e `app/domain/reporting/trend.py`.
- [ ] Lasciare shim in `app/utils/pii.py` e `app/utils/trend_render.py`.
- [ ] Aggiornare consumer (`discord_adapter`, `triggers`, `barcello`, `summary renderers`).
- [ ] Rieseguire `tests/test_pii_and_triggers.py` e i test summary/barcello correlati.

### Fase 5 — Migrare feature Activity

- [ ] Creare `app/features/activity/{commands,services,renderers}`.
- [ ] Spostare `attivita.py`, `activity_insights.py`, `daily_activity_report.py`, `daily_activity_sorting.py`, `activity_daily_report_renderer.py`, `activity_dm_renderer.py`, `user_activity_renderer.py`.
- [ ] Lasciare shim in `app/renderers/` e, se necessario, nei vecchi `app/services/`.
- [ ] Aggiornare `tests/test_activity_daily_report_renderer.py`, `tests/test_activity_dm_renderer.py`, `tests/test_activity_display_names.py`.

### Fase 6 — Migrare feature Summary

- [ ] Creare `app/features/summary/{commands,services,renderers}`.
- [ ] Spostare `resoconto.py`, `riassunto.py`, `summary.py`, `channel_summary.py`, `daily_resoconto.py`, `channel_summary_renderer.py`, `daily_resoconto_renderer.py`, `summary_render.py`, `summary_names.py`.
- [ ] Tenere `daily_resoconto_renderer.py` come shim legacy finché non viene confermato se è ancora usato indirettamente.
- [ ] Aggiornare `tests/test_resoconto_channel_summary_regressions.py` e i test riassunto/resoconto pertinenti.

### Fase 7 — Migrare Aura / Barcello / Triggers

- [ ] Creare `app/features/aura/`, `app/features/barcello/`, `app/features/triggers/`.
- [ ] Spostare comandi + servizi relativi mantenendo i vecchi entrypoint come shim.
- [ ] Consolidare tutti i riferimenti config verso `settings/`.
- [ ] Aggiornare `tests/test_aura.py`, `tests/test_aura_render.py`, `tests/test_config_file_loader.py`, `tests/test_pii_and_triggers.py`.

### Fase 8 — Cleanup finale

- [ ] Rimuovere i duplicati sotto `app/settings/`.
- [ ] Rimuovere i compatibility shims Python rimasti in `app/renderers/`, `app/utils/`, `app/services/`.
- [ ] Aggiornare eventuali import residui usando una ricerca globale su `app.renderers`, `app.utils`, `app/services.config_*`, `app/settings/`.
- [ ] Rieseguire l'intera suite.

---

## 8) Ordine raccomandato dei benefici

Se l'obiettivo è massimizzare rapporto beneficio/rischio, l'ordine migliore è:

1. **config centralization** (`app/settings/*` → `settings/*`)
2. **estrazione `app/config/`**
3. **estrazione shared Discord infra**
4. **feature Activity**
5. **feature Summary**
6. **feature Aura / Barcello / Triggers**
7. **rimozione shim e duplicati**

Così si ottiene prima la semplificazione più urgente (`settings/` unico) e solo dopo il refactor più ampio dei moduli.


---

## 7) Stato finale del cleanup + validator

Stato target dopo questa PR finale:

- `settings/` resta l'unica root canonica per i config file-based versionati e locali.
- `app/renderers/` non deve più ospitare renderer feature-specific: i renderer canonici vivono sotto `app/features/*/renderers/`.
- `app/utils/` non deve più ricevere helper di dominio/shared già migrati in `app/shared/` o `app/domain/`.
- gli import interni devono puntare ai package canonici (`app/config`, `app/shared`, `app/domain`, `app/features/*`) invece che ai vecchi shim legacy.

### 7.1 Regole del validatore `scripts/validate_project_layout.py`

Il validatore applica queste regole:

- **ERROR** se compare un nuovo file sotto `app/settings/`;
- **ERROR** se compare il literal hardcoded `app/settings/` fuori dalle eccezioni documentate (`README`, `settings/README.md`, documenti storici di audit/refactor);
- **ERROR** se ricompare un renderer applicativo sotto `app/renderers/`;
- **ERROR** se ricompare un helper improprio sotto `app/utils/`;
- **ERROR** se un file Python viola la naming scheme attuale basata su `snake_case`;
- **ERROR** se in aree feature compaiono di nuovo filename legacy/alias invece del filename canonico introdotto dal refactor;
- **ERROR** se viene aggiunto un nuovo template `settings/*.example.json` senza aggiornare il catalogo ammesso dal validatore;
- **WARNING** per ogni compatibility shim legacy ancora presente nel codice.

### 7.2 Eccezioni documentate

Le uniche occorrenze ammesse del literal `app/settings/` sono quelle strettamente documentali/storiche, necessarie per spiegare la migrazione:

- `README.md`;
- `settings/README.md`;
- `docs/project_structure_refactor_plan.md`;
- `docs/test_suite_audit.md`.

L'obiettivo è evitare nuovi riferimenti operativi al path legacy senza perdere il contesto storico della migrazione.
