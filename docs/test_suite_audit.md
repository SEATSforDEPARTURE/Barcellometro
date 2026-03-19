# Audit della suite di test

Data audit: 2026-03-19.

## 1. Panoramica generale della suite

### Metodo usato
- Analisi statica dell'intera cartella `tests/` file per file.
- Confronto puntuale con l'architettura attuale sotto `app/`, in particolare `app/plugins/commands_modular/`, `app/services/`, `app/renderers/`, `app/shared/discord/`, `app/config/` e il package minimale `app/utils/`.
- Verifica di collection/esecuzione con:
  - `pytest --collect-only -q`
  - `pytest -q`
  - `PYTHONPATH=. pytest --collect-only -q`
  - `PYTHONPATH=. pytest -q`

### Stato reale della suite
- La suite contiene **58 file** di test.
- Con esecuzione "naive" (`pytest -q`) la suite non è eseguibile: diversi moduli falliscono già in collection perché `app` non è in `PYTHONPATH`.
- Con `PYTHONPATH=. pytest --collect-only -q` vengono raccolti **295 test**, ma la collection si interrompe comunque con **8 errori**.
- Gli errori residui non dipendono solo da dipendenze mancanti (`httpx`, `faster_whisper`), ma anche da **contaminazione tra test** via `sys.modules` e stub incompleti di moduli condivisi.

### Valutazione sintetica
La suite è **ampia** e copre bene diverse aree di dominio pure o quasi-pure (Aura, scheduler core, footer meta, DB voice, QnA engine, entitlements), ma nel complesso oggi **non è pienamente affidabile** dopo i refactor recenti per quattro motivi principali:
1. **Bootstrapping fragile**: manca una configurazione pytest esplicita per import path e dipendenze test/dev.
2. **Contaminazione globale**: più file patchano `sys.modules` a livello modulo e lasciano stub incompleti per moduli shared.
3. **Troppi test source-based**: molti file verificano stringhe nel sorgente invece del comportamento reale.
4. **Bypass dell'architettura corrente**: alcuni test caricano moduli con `importlib.util.spec_from_file_location(...)` / `exec_module(...)`, aggirando package init, import graph e registrazione reale dei componenti.

### Distribuzione per classificazione
- **AFFIDABILE**: 19 file.
- **FRAGILE**: 23 file.
- **SOSPETTO**: 10 file.
- **OBSOLETO / DA RISCRIVERE**: 6 file.

> Criterio adottato:
> - **AFFIDABILE** = allineato all'architettura attuale, abbastanza isolato e behavior-oriented.
> - **FRAGILE** = utile ma sensibile a dipendenze, import side effects, mock/stub globali o dettagli implementativi.
> - **SOSPETTO** = passa facilmente anche se il comportamento reale è rotto, oppure fallisce per refactor innocui.
> - **OBSOLETO / DA RISCRIVERE** = forte odore legacy, bypass del package/loading reale o contaminazione tale da renderlo poco difendibile.

## 2. Elenco file test con classificazione

| File | Classificazione | Nota sintetica |
|---|---|---|
| `tests/test_activity_daily_report_renderer.py` | FRAGILE | Test utile ma dipende da import chain pesante: il renderer trascina `commands_modular` e quindi dipendenze non pertinenti (`httpx`). |
| `tests/test_activity_display_names.py` | FRAGILE | Behavior test sensato, ma appoggiato a stub globali e alla stessa import chain indiretta dei renderer/activity modules. |
| `tests/test_activity_dm_renderer.py` | FRAGILE | Copertura buona del renderer, ma isolamento incompleto e dipendenza da import side effects. |
| `tests/test_admin_ai_commands.py` | SOSPETTO | Solo assert su stringhe del sorgente di `admin.py`; molto sensibile a refactor cosmetici, naming o formattazione. |
| `tests/test_ai_model_catalog.py` | FRAGILE | Verifica comportamento reale, ma usa stub globali per dipendenze esterne a livello modulo. |
| `tests/test_ai_service_providers.py` | FRAGILE | Valido sul routing provider/fallback, ma fortemente mockato e con stub globali di `httpx`/`openai`. |
| `tests/test_ai_task_models.py` | FRAGILE | Copre routing/fallback per task AI, ma con mock permissivi può passare anche se il contratto reale verso i provider è rotto. |
| `tests/test_ai_web_search.py` | FRAGILE | Utile sui flag/task AI, ma molto dipendente da stub di provider e non testa davvero l'integrazione tool/web. |
| `tests/test_attivita_user_report.py` | OBSOLETO / DA RISCRIVERE | Carica il modulo con `spec_from_file_location` / `exec_module`, bypassa package init e architettura corrente; alto odore legacy. |
| `tests/test_audio_notes_commands.py` | OBSOLETO / DA RISCRIVERE | Inietta stub globali incompleti in `sys.modules` per moduli shared (`command_embeds`, `command_helpers`, ecc.) e contamina la suite. |
| `tests/test_audio_notes_transcribe.py` | FRAGILE | Fixture con monkeypatch ben mirata, ma il modulo è comunque caricato manualmente via `importlib.util` e non tramite import reale. |
| `tests/test_aura.py` | AFFIDABILE | Buona copertura behavior/db/domain logic su Aura, con fake database mirati e test sostanziali. |
| `tests/test_aura_render.py` | AFFIDABILE | Copertura profonda del rendering Aura, centrata su output e limiti reali dell'embed. |
| `tests/test_barcello_event_driven.py` | FRAGILE | Buoni scenari di dominio, ma dipende dal grosso modulo `triggers` e quindi soffre la contaminazione di altri test. |
| `tests/test_barcello_service.py` | AFFIDABILE | Unit test semplici, mirati e poco fragili. |
| `tests/test_barcello_window.py` | AFFIDABILE | Copertura piccola ma pulita su funzioni pure. |
| `tests/test_campaign_content_command_behaviors.py` | FRAGILE | Testa comportamento utile, ma tramite modulo caricato a mano e stub parziali di moduli shared/scheduler. |
| `tests/test_campaign_content_commands.py` | SOSPETTO | Solo pattern sul sorgente di `messaggi.py` / `triggers.py`; bassa affidabilità rispetto al comportamento reale di registrazione slash commands. |
| `tests/test_campaign_content_editorial_pipeline.py` | FRAGILE | Copertura buona della pipeline editoriale, ma con stub globali di dipendenze e patch interne molto permissive. |
| `tests/test_campaign_content_embed_footer.py` | SOSPETTO | Mix di test buoni su formatter e di assert testuali sul sorgente del service; qualità disomogenea. |
| `tests/test_campaign_content_pagination.py` | AFFIDABILE | Verifica comportamento UI/view abbastanza reale e orientato agli outcome. |
| `tests/test_campaign_content_scheduler_and_db.py` | SOSPETTO | Quasi interamente source-based; non verifica davvero DB schema/runtime scheduler. |
| `tests/test_command_standard_validator.py` | AFFIDABILE | Usa il validatore reale del repository e controlla output strutturato, con valore architetturale concreto. |
| `tests/test_commands_namespace_refactor.py` | SOSPETTO | Conferma refactor solo via string matching nel sorgente di `commands.py`. |
| `tests/test_config_file_loader.py` | AFFIDABILE | Isolato con `tmp_path`/`monkeypatch.chdir`, allineato al codice attuale e centrato sul comportamento. |
| `tests/test_config_overrides.py` | AFFIDABILE | Test piccolo ma coerente e ben isolato. |
| `tests/test_daily_activity_report_pagination.py` | FRAGILE | Unisce un paio di behavior test utili a molti assert sul sorgente + stub globale di `discord`. |
| `tests/test_daily_activity_sorting.py` | FRAGILE | Test su funzioni pure, ma carica il modulo con `spec_from_file_location` senza bisogno reale. |
| `tests/test_entitlements.py` | AFFIDABILE | Copertura buona del dominio entitlements, ben focalizzata. |
| `tests/test_entitlements_example.py` | AFFIDABILE | Verifica concreta dell'esempio runtime e del payload di configurazione. |
| `tests/test_footer_meta.py` | AFFIDABILE | Ottima copertura della pipeline footer/meta e dei casi multi-embed. |
| `tests/test_footer_status_variants.py` | SOSPETTO | Parte utile sulle helper functions, ma metà file è source-based e iper-sensibile a refactor innocui. |
| `tests/test_import_smoke.py` | FRAGILE | Fa solo smoke import con stub globali; valore basso e rischio di mascherare problemi reali di wiring. |
| `tests/test_inactive_members_moderation_state.py` | FRAGILE | Test piccolo ma dipende da stub globali `discord`/`aiosqlite` per una funzione banale. |
| `tests/test_instance_mode.py` | OBSOLETO / DA RISCRIVERE | Per testare una helper pura importa `app.core.bot`, trascinando STT/faster-whisper: segnale netto di mancato allineamento architetturale. |
| `tests/test_member_flow_notifications.py` | FRAGILE | Mescola behavior test utili con import hacking, monkeypatch di `builtins.__import__` e assert sul sorgente. |
| `tests/test_message_scheduler.py` | AFFIDABILE | Uno dei file migliori: copre logica scheduler, CRUD DB e footer metadata in modo concreto. |
| `tests/test_moderation_actions_db.py` | AFFIDABILE | Buona copertura su backward compatibility DB e liste moderazione con fake `aiosqlite` ragionevole. |
| `tests/test_moderazione_utenti_commands.py` | SOSPETTO | Controlla solo stringhe nel sorgente dei namespace/nomi comando. |
| `tests/test_pii_and_triggers.py` | OBSOLETO / DA RISCRIVERE | File monolitico, molti stub globali a livello modulo, ampio rischio di contaminazione e mismatch con interfacce condivise attuali. |
| `tests/test_prompt_campaign_commands.py` | FRAGILE | Verifica behavior utile, ma patcha globali di modulo (`check_permission`) e asserisce raw text invece del rendering standard. |
| `tests/test_qna_ask_inputs.py` | OBSOLETO / DA RISCRIVERE | Caricamento manuale del modulo ask con stub globali legacy di `ctx` e `permissions`; bypass dell'import path reale. |
| `tests/test_qna_followup_persistence.py` | FRAGILE | Il repository è ben testato, ma il file importa anche `TriggerEngineService` e soffre la fragilità del modulo `triggers`. |
| `tests/test_qna_query_engine.py` | AFFIDABILE | Copertura behavior-oriented e sostanziale del motore QnA. |
| `tests/test_qna_session_store.py` | AFFIDABILE | Test puliti su store TTL e touch. |
| `tests/test_resoconto_channel_summary_regressions.py` | FRAGILE | Mix di regressioni utili e assert testuali sul sorgente/SQL; buona intenzione, isolamento medio. |
| `tests/test_resoconto_riassunto_source_regressions.py` | SOSPETTO | Interamente source-based; protegge refactor visivi, non comportamento reale. |
| `tests/test_resoconto_riassunto_standardization.py` | FRAGILE | Buoni scenari, ma enorme monkeypatching del modulo `commands` e forte dipendenza dal wiring interno. |
| `tests/test_scheduler_utils.py` | AFFIDABILE | Funzioni pure, test diretti e stabili. |
| `tests/test_settings_paths_docs.py` | SOSPETTO | Verifica documentazione e file env con assunzioni testuali che possono diventare obsolete senza impatto runtime. |
| `tests/test_sqlite_lock_and_scheduler_resilience.py` | AFFIDABILE | Copertura preziosa su lock SQLite, retry e resilienza scheduler. |
| `tests/test_summary_ai_provider_compat.py` | FRAGILE | Copertura importante su compat AI/provider, ma con stub esterni e mock molto permissivi. |
| `tests/test_summary_footer_semantics.py` | SOSPETTO | Asserisce righe/variabili del sorgente invece dell'effetto osservabile della footer pipeline. |
| `tests/test_trigger_phrases_global.py` | FRAGILE | Copertura funzionale rilevante, ma molto dipendente dal modulo `triggers` e quindi vulnerabile a contaminazione/import side effects. |
| `tests/test_triggers_and_roles_regressions.py` | OBSOLETO / DA RISCRIVERE | Caricamento manuale di due moduli con `spec_from_file_location`, stub globali e coupling forte a dettagli interni. |
| `tests/test_voice_ingest_utils.py` | AFFIDABILE | Test minimali ma ben isolati. |
| `tests/test_voice_participant_events.py` | AFFIDABILE | Integrazione DB concreta e poco fragile. |
| `tests/test_voice_sessions_cleanup.py` | AFFIDABILE | Integrazione DB concreta, rappresentativa dei vincoli critici di cleanup voice. |

## 3. Problemi strutturali trovati

### 3.1 Bootstrapping pytest non dichiarato
- Il repository non espone una configurazione pytest (`pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`) che imposti `PYTHONPATH` o il modo corretto di inizializzare l'app.
- Di fatto la suite richiede conoscenza implicita del comando corretto (`PYTHONPATH=. pytest ...`), quindi il semplice "pytest passa" non è oggi un criterio attendibile.

### 3.2 Import side effects troppo forti
- `app/plugins/commands_modular/__init__.py` importa direttamente quasi tutti i moduli comando.
- Questo fa sì che import apparentemente innocui (per esempio un renderer che usa una helper sotto `commands_modular`) trascinino AI catalog, provider esterni o servizi non necessari al test.
- Effetto pratico osservato: un test dei renderer di activity può fallire per `httpx` mancante, cioè per una dipendenza che non appartiene al dominio testato.

### 3.3 Contaminazione via `sys.modules`
- Più file mutano `sys.modules` a livello modulo, non in fixture isolate/undo-safe.
- I casi più rischiosi sono:
  - `tests/test_audio_notes_commands.py`
  - `tests/test_qna_ask_inputs.py`
  - `tests/test_pii_and_triggers.py`
  - `tests/test_daily_activity_report_pagination.py`
  - `tests/test_import_smoke.py`
  - diversi file AI che registrano stub di `openai`, `httpx`, `aiosqlite`
- La contaminazione osservata più grave è su moduli shared:
  - `app.shared.discord.command_embeds`
  - `app.plugins.commands_modular.command_helpers`
- Durante la collection reale questo produce errori come:
  - impossibilità di importare `CommandEmbedSection` da `app.shared.discord.command_embeds`
  - impossibilità di importare `add_group_once` da `app.plugins.commands_modular.command_helpers`

### 3.4 Uso di `spec_from_file_location(...)` / `exec_module(...)`
- È presente in file chiave: `attivita_user_report`, `audio_notes_commands`, `audio_notes_transcribe`, `campaign_content_command_behaviors`, `daily_activity_sorting`, `qna_ask_inputs`, `triggers_and_roles_regressions`.
- Questo pattern aggira:
  - package init reali,
  - import graph corrente,
  - side effects dichiarati dal package,
  - eventuali compatibility shim o refactor di namespace.
- È un forte indicatore che quei test si sono adattati a refactor precedenti "forzando" il caricamento, invece di restare coerenti con l'architettura corrente.

### 3.5 Troppi test source-based
- Molti file non testano il comportamento, ma la presenza/assenza di stringhe nel sorgente.
- Tipologie ricorrenti:
  - nomi di slash command nel codice;
  - decorator presenti/assenti;
  - commenti o helper function nominate in un certo modo;
  - frammenti testuali di implementazione interna.
- Conseguenze:
  - **falsi negativi** dopo refactor innocui (rename di variabile, helper estratta, formattazione diversa);
  - **falsi positivi** se il pattern resta nel file ma il wiring reale è rotto.

### 3.6 Mock/stub troppo permissivi
- Alcuni test AI e di command layer patchano provider/service con `AsyncMock` che restituiscono payload già "perfetti".
- In questi casi il test verifica soprattutto che il metodo mockato venga chiamato, non che la forma del payload o l'integrazione resti compatibile con il contratto reale.

### 3.7 Copertura disomogenea tra domain layer e command layer
- I servizi/domain più puri sono mediamente ben coperti.
- Il command layer modulare e il wiring slash command sono coperti in larga parte da test source-based o da caricamenti manuali del modulo.
- Quindi proprio le aree recentemente refactorate (namespace, naming, registration) sono spesso protette da test **fragili o sospetti**, non da vere prove di comportamento.

## 4. Test probabilmente non aggiornati dopo i refactor recenti

Questi file mostrano i segnali più forti di disallineamento con l'architettura attuale:

### Priorità alta
- `tests/test_audio_notes_commands.py`
  - stubba `app.shared.discord.command_embeds` senza l'interfaccia completa attuale;
  - stubba `command_helpers` e altri moduli shared in modo parziale;
  - carica `audio_notes.py` fuori dal package reale.
- `tests/test_qna_ask_inputs.py`
  - stesso pattern legacy di caricamento manuale;
  - bypass del namespace reale e delle dipendenze correnti del comando `ask`.
- `tests/test_triggers_and_roles_regressions.py`
  - carica `roles.py` e `triggers.py` via `spec_from_file_location`;
  - è molto sensibile a refactor innocui dei moduli e del package.
- `tests/test_attivita_user_report.py`
  - stesso odore di caricamento manuale/legacy;
  - protegge helper specifiche ma non il wiring reale del comando modulare.
- `tests/test_instance_mode.py`
  - una helper purissima (`normalize_instance_mode`) dovrebbe essere testabile senza importare tutto `app.core.bot` e trascinare STT/faster-whisper.
- `tests/test_pii_and_triggers.py`
  - file omnibus, nato probabilmente prima dell'attuale decomposizione dei moduli;
  - oggi è troppo ampio, troppo globale e troppo accoppiato.

### Priorità media
- `tests/test_admin_ai_commands.py`
- `tests/test_campaign_content_commands.py`
- `tests/test_commands_namespace_refactor.py`
- `tests/test_moderazione_utenti_commands.py`
- `tests/test_resoconto_riassunto_source_regressions.py`
- `tests/test_summary_footer_semantics.py`
- `tests/test_settings_paths_docs.py`

Questi non sono necessariamente "rotti" oggi, ma proteggono soprattutto il testo del sorgente com'era al momento del refactor, non il comportamento corrente del sistema.

## 5. Test che rischiano falsi positivi / falsi negativi

### Rischio forte di falsi positivi
Passano anche se il comportamento reale è rotto o fortemente degradato.

- `tests/test_admin_ai_commands.py`
- `tests/test_campaign_content_commands.py`
- `tests/test_campaign_content_scheduler_and_db.py`
- `tests/test_commands_namespace_refactor.py`
- `tests/test_moderazione_utenti_commands.py`
- `tests/test_resoconto_riassunto_source_regressions.py`
- `tests/test_summary_footer_semantics.py`
- `tests/test_settings_paths_docs.py`

Motivo comune: testano il **sorgente come testo**, non il comando/servizio in esecuzione.

Inoltre:
- `tests/test_ai_task_models.py`
- `tests/test_ai_service_providers.py`
- `tests/test_ai_web_search.py`
- `tests/test_summary_ai_provider_compat.py`

rischiano falsi positivi perché i mock provider sono molto permissivi e non convalidano davvero l'interfaccia reale delle chiamate esterne.

### Rischio forte di falsi negativi
Possono fallire anche se il comportamento reale è corretto.

- tutti i file source-based sopra elencati: basta una rinomina innocua o l'estrazione di una helper;
- `tests/test_audio_notes_commands.py`, `tests/test_qna_ask_inputs.py`, `tests/test_triggers_and_roles_regressions.py`, `tests/test_attivita_user_report.py`: basta un refactor del package/import graph;
- `tests/test_resoconto_riassunto_standardization.py`: monkeypatch massivo del modulo `commands`, quindi refactor interni non comportamentali possono romperlo;
- `tests/test_member_flow_notifications.py`: monkeypatch di `builtins.__import__` può fallire per motivi incidentali;
- `tests/test_prompt_campaign_commands.py`: oggi asserisce raw string message e non il formato standard di risposta, quindi è sensibile a refactor di output legittimi.

## 6. Gap di copertura

### 6.1 Comandi modulari principali
Copertura presente ma non abbastanza solida dove servirebbe davvero:
- **ben coperti a livello dominio, poco a livello command wiring**:
  - `barcello`
  - `attivita`
  - `riassunto`
  - `resoconto`
  - `triggers`
- **scoperti o quasi scoperti come command behavior reale**:
  - `audio_notes`
  - `privacy`
  - `settings`
  - `status`
  - `stt`
  - `translate`
  - `voice_ingest`
  - `time_windows`

### 6.2 Footer / meta / footer pipeline
Buona copertura su `FooterService` e metadata embed (`tests/test_footer_meta.py`), ma mancano o sono deboli:
- test del patching reale di `install_footer_auto_finalize(...)` su oggetti Discord;
- test diretti dei moduli shared sotto `app/shared/discord/footer_pipeline.py`, `app/shared/discord/command_embeds.py`, `app/shared/discord/embed_limits.py`, `app/shared/discord/report_embeds.py`, `app/shared/discord/component_notices.py`, `app/shared/discord/delivery.py`.

### 6.3 Scheduling
Ben coperti:
- `scheduler_utils`
- parte core di `message_scheduler`
- resilienza SQLite/retry

Mancano o sono deboli:
- comportamento end-to-end di `process_due_services` e scheduler editoriale (oggi protetto soprattutto da source-based checks);
- integrazione completa tra DB schedule, campaign content service e footer pipeline.

### 6.4 Triggers
Copertura ampia ma troppo fragile.
Mancano test puliti e affidabili su:
- alias legacy/permission routing nel command layer;
- wiring dei trigger command groups senza caricamenti manuali;
- compatibilità di stato/shared helpers dopo refactor dei moduli shared.

### 6.5 Activity / resoconto / riassunto
- I renderer e diverse funzioni di dominio sono coperti.
- Manca una copertura davvero affidabile del comportamento reale dei comandi modulari e della standardizzazione delle risposte slash dopo il refactor.

### 6.6 Aura
- L'area Aura è una delle meglio coperte a livello servizi e rendering.
- Gap residuo: command layer Aura e integrazione con entitlements/permissions in registrazione slash reale.

### 6.7 AI model routing / fallback
- Buona copertura unitaria del routing.
- Gap importanti:
  - nessun test di contratto con provider reali o fake-client più rigorosi;
  - nessun test che verifichi la forma effettiva dei payload inviati alle API in modo robusto senza basarsi solo su `AsyncMock`.

### 6.8 Compatibility shims legacy
Gap evidente:
- l'uso di alias legacy per path/config e command permission non è coperto in modo sistematico;
- `app/config/file_loader.py` e `app/config/overrides.py` hanno copertura di base, ma non esiste una batteria dedicata alle sole compatibilità legacy documentate;
- le compatibilità legacy di `voice_ingest` per setting namespaced/legacy non risultano coperte;
- diversi alias legacy di permission/command nei moduli comando non sono testati in modo affidabile.

## 7. Contaminazione tra test e dipendenze implicite

### 7.1 Test che possono contaminare altri test durante collection/execution
I principali candidati sono:
- `tests/test_audio_notes_commands.py`
- `tests/test_qna_ask_inputs.py`
- `tests/test_pii_and_triggers.py`
- `tests/test_import_smoke.py`
- `tests/test_daily_activity_report_pagination.py`
- `tests/test_member_flow_notifications.py` (meno per `sys.modules`, più per import monkeypatching)

Motivi:
- scrivono in `sys.modules` a livello modulo;
- non ripristinano sempre l'interfaccia originaria;
- usano stub incompleti per moduli shared che altri test importano realmente.

### 7.2 Dipendenza implicita da import side effects
**Sì, presente e significativa.**
Esempi:
- import di `commands_modular` che trascina più moduli del necessario;
- import di `app.core.bot` per testare una helper di instance mode;
- import dei renderer activity che trascinano moduli comando e AI catalog.

### 7.3 Dipendenza implicita da stato globale
**Sì, presente.**
Principali forme:
- `sys.modules` patchato globalmente;
- monkeypatch diretto di attributi di modulo (`check_permission`, classi Discord, ecc.);
- alcuni stub `discord` condivisi tra file.

### 7.4 Dipendenza implicita da DB condiviso
**Bassa**, ma non nulla.
- Molti test DB usano `:memory:` o fake connection => bene.
- Non ho trovato dipendenza sistematica da un DB condiviso su disco.
- La criticità è più sul lato `aiosqlite` stubbato globalmente che sul database condiviso in sé.

### 7.5 Dipendenza implicita da filesystem condiviso
**Media**.
- I source-based test leggono direttamente i file del repo e quindi dipendono dallo stato del working tree.
- `test_config_file_loader.py` isola bene il cwd via `monkeypatch.chdir(tmp_path)`.
- Alcuni test documentali/source-based non isolano nulla perché per definizione leggono il filesystem reale del repository.

### 7.6 Dipendenza implicita da environment variables non isolate
**Bassa**.
- Non emergono molti test che leggono/scrivono env vars.
- Il problema principale è più `PYTHONPATH` implicito che env var mutate durante i test.

## 8. Piano di remediation prioritizzato

### Quick wins
1. **Aggiungere configurazione pytest esplicita**
   - impostare `pythonpath = .` o equivalente;
   - documentare dipendenze dev/test minime.
2. **Introdurre fixture centrali per stub esterni**
   - `aiosqlite`, `openai`, `httpx`, `faster_whisper`, `discord`;
   - vietare stub globali ad hoc nei singoli file quando non strettamente necessari.
3. **Ridurre subito i test source-based più deboli**
   - iniziare da `test_admin_ai_commands.py`, `test_commands_namespace_refactor.py`, `test_moderazione_utenti_commands.py`, `test_summary_footer_semantics.py`.
4. **Separare i test documentali/source-based dai test runtime**
   - almeno con naming/marker distinti (`@pytest.mark.source_contract`).

### Fix importanti
1. **Riscrivere i test che caricano moduli con `spec_from_file_location`**
   - migrare verso import reali del package;
   - se servono isolation points, usare fixture o dependency injection, non module loading manuale.
2. **Eliminare la contaminazione di `sys.modules`**
   - spostare tutte le patch in fixture `monkeypatch` con teardown automatico;
   - rendere completi gli stub dei moduli shared oppure, meglio, smettere di stubbarli globalmente.
3. **Spezzare `tests/test_pii_and_triggers.py`**
   - separare PII, heuristics, trigger phrase handling, qna legacy compat e polling barcello in file distinti.
4. **Testare il wiring dei command group via oggetti `discord.app_commands.Group` reali**
   - invece di cercare stringhe nel sorgente.
5. **Ridurre il coupling dell'import graph applicativo**
   - in particolare evitare che import minori trascinino provider AI o moduli pesanti.

### Test da riscrivere per primi
1. `tests/test_audio_notes_commands.py`
2. `tests/test_qna_ask_inputs.py`
3. `tests/test_triggers_and_roles_regressions.py`
4. `tests/test_attivita_user_report.py`
5. `tests/test_instance_mode.py`
6. `tests/test_pii_and_triggers.py`

## 9. Regole proposte per mantenere affidabile la suite in futuro

1. **Niente `spec_from_file_location(...)` / `exec_module(...)` nei test applicativi**, salvo casi eccezionalissimi e documentati.
2. **Niente patch dirette a `sys.modules` a livello modulo**; usare fixture `monkeypatch` con teardown.
3. **I moduli shared (`footer`, `scheduler_utils`, `command_embeds`, ecc.) non vanno stubbatI parzialmente**: o si usa l'implementazione reale, o uno stub completo/contrattuale centralizzato.
4. **Preferire test di comportamento a test di sorgente**. Se proprio serve un test source-based, marcarlo esplicitamente come contratto strutturale e tenerlo minimale.
5. **Ogni command refactor deve avere almeno un test di registrazione runtime** su `discord.app_commands.Group`, non solo assert sulle stringhe nel file.
6. **Ogni refactor di naming/path deve aggiornare anche i test di import, non aggirarli** con caricamenti manuali del modulo.
7. **Le dipendenze esterne devono avere fake/stub condivisi a livello suite**, non reinventati per file.
8. **Le helper pure vanno collocate in moduli import-light**, così i loro test non trascinano bot, STT o provider AI.
9. **Separare i test per livello**:
   - unit/domain
   - integration DB
   - command wiring
   - source/documentation contracts
10. **Aggiungere un controllo CI sulla collection pulita**
    - `PYTHONPATH=. pytest --collect-only -q`
    - obiettivo: zero errori di collection prima ancora dell'esecuzione completa.

## Conclusione operativa

La suite non è da buttare: contiene diversi blocchi molto buoni e già utili come rete di sicurezza reale. Però, dopo i refactor recenti di comandi/output/path/naming, la protezione è oggi **fortemente sbilanciata**:
- buona sul dominio puro;
- mediocre sul wiring reale dei comandi;
- fragile sul piano dell'isolamento;
- troppo dipendente da test che leggono il sorgente anziché esercitare il comportamento.

Se l'obiettivo è capire se la suite è davvero aggiornata, affidabile e utile, la risposta è:
- **parzialmente sì** per Aura, scheduler core, footer meta, voice DB, QnA engine, entitlements;
- **no, non ancora** per una parte importante del command layer refactorato e per i file che usano import hacking / stub globali.
