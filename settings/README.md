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
- Il namespace canonico per la configurazione di rendering centralizzata è `/embed`, non `/admin footer`: footer e author sono domini distinti ma centralizzati e seguono la precedenza `override servizio > globale > fallback`.
- Il fallback author per servizio resta sempre `emoji servizio + nome servizio`; il reset deve tornare a questo fallback di dominio quando non esistono override o template globali.
- Le thumbnail author e footer sono separate: override o template del footer non devono fungere da fallback implicito per l'author, e viceversa.
- Gli override locali non devono reintrodurre wording legacy nei footer o nei template: `Dati elaborati` + ` in loco` ed `e fallback` + ` locale` sono aboliti in tutto il progetto.
- Se un file runtime come `settings/barcello_trigger.json` contiene campi come `footer`, `fallback_footer` o simili, per output non-AI non va salvata alcuna frase tecnica finale equivalente; per output AI si usa solo `Dati elaborati con ...` quando esistono davvero contributor/provider/model da dichiarare.
- Per il sottosistema `/inactivity dms` i comandi canonici documentati sono `template_grace_*` e `template_tempban_*`; chiavi legacy interne come `dm_reminder_template` / `dm_kick_template` restano solo di compatibilità storage/runtime e non fanno parte della surface slash pubblica.
- I template DM di `/inactivity dms` e `/users dms` supportano esplicitamente `{mention}` (oltre ai placeholder storici come `{user}`, `{username}`, `{display_name}`), così il bot può taggare il destinatario direttamente nel DM.

## Note specifiche per `settings/greetings_trigger.example.json`

- Le chiavi template GREETINGS sono quelle canoniche del dominio: `join`, `leave`, `kick`, `ban`, `tempban`, `grace`, `inactive_kick`, `inactive_tempban`, `inactive_grace`.
- `kick` resta la chiave tecnica di compatibilità, ma il wording user-facing deve essere `allontanamento`.
- Il file governa solo copy e variazioni mood/time/count/barcello: non ridefinisce il layout live di `🚪 INGRESSI & USCITE`, che ora usa author standard via metadata canonici, titolo embed = label evento, narrativa in description, thumbnail = avatar utente e nessun campo separato `Evento`.
- Le label titolo GREETINGS sono fisse per tipo evento (`ENTRATA`, `USCITA`, `ESPULSIONE`, `INTERDIZIONE PERENNE`, `INTERDIZIONE TEMPORANEA`, `GRAZIA`): niente varianti prima/successive e niente conteggio nel titolo.
- Lo schema editoriale definitivo è `event_templates`: una grammatica a slot fissi (`opening`, `action_phrase`, `occurrence_phrase`, `detail_phrase`, `barcello_phrase`, `closing_comment`) che produce **una sola description narrativa**.
- `opening` deve partire da `{mention}`: la mention utente resta sempre all'inizio della description.
- `barcello_phrase` va usata solo per `leave` (uscita volontaria), non per ban/kick/tempban/grazia.
- I casi moderativi (`kick`, `ban`, `tempban`, `grace`, `inactive_kick`, `inactive_grace`) usano il field unico `👇 __**LA MODERAZIONE AGGIUNGE**__` solo quando esiste una nota utile reale (`greetings_reason`/reason renderizzata dopo normalizzazione: niente `None`, vuoto o placeholder). La description non deve duplicare quel contenuto. `inactive_tempban` è il caso speciale automatico per inattività e non mostra il field.
- Il vecchio campo separato `Stato barcello "<server>"` non esiste più: ogni riferimento barcello resta nella description narrativa e solo dove previsto dal contratto.
- Per il testo narrativo è consigliato usare `{mention}` invece di `{display_name}` quando il soggetto deve comparire come tag utente.
- Le occorrenze lette nei placeholder (`{occurrence_number}`, `{occurrence_ordinal}`, `{event_label}`) arrivano dalla timeline canonica `member_flow_events`, non dal ledger raw `moderation_actions`.
- La struttura example aggiornata è pensata come source of truth editoriale unica ed esplicita: nessuna frase user-facing GREETINGS deve più arrivare da template legacy salvati nel database o da copy hardcoded parallelo.
  - `docs.placeholders` documenta i placeholder supportati e gli alias legacy compatibili;
  - `defaults.fallbacks` garantisce un fallback robusto per ogni `event_type_key`;
  - `event_templates[event_type_key]` contiene la baseline narrativa generale;
  - `first_occurrence` e `repeat` distinguono il primo ingresso dai rientri, e più in generale prima occorrenza vs successive;
  - `moods -> time -> barcello -> count` permette override sempre più specifici senza reintrodurre campi separati nell'embed.
- Nei `event_templates` narrativi ogni slot può essere stringa o lista: le liste vengono variate in modo deterministico (seed su evento/mood/finestra/barcello/occorrenza) per aumentare varietà senza output casuale instabile.
- Per i commenti finali è supportato anche `moods.<mood>.event_templates.<event_type>`: quando presente sovrascrive solo gli slot dichiarati (tipicamente `closing_comment`) mantenendo intatta la grammatica narrativa base.
- Il resolver dei template segue una cascata precisa: override più specifici (`mood` + `time` + `barcello` + `count`) → override medi → `templates[...]` → `defaults.fallbacks[...]`.
- La grammatica evento resta canonica e coerente col renderer live: `kick` / `inactive_kick` sono chiavi tecniche, ma le etichette e le frasi user-facing devono parlare di `allontanamento`, mai di `KICK`.
- I flussi di moderazione del bot (`/mod users ...`) e la moderazione nativa Discord devono convergere nella stessa timeline canonica `member_flow_events`: il feed deve mostrare solo l'evento dedicato (`BAN`, `ALLONTANAMENTO`, `BAN TEMPORANEO`, `USCITA`) senza embed duplicati della stessa sequenza tecnica.
- `unban` deve essere tracciato sia nel raw log sia nel mirror canonico per audit, backfill e pulizia coerente dello stato ban/tempban, ma non deve comparire nel feed GREETINGS come uscita o rientro visibile.
- Quando esiste una `greetings_reason` (o reason equivalente), il renderer GREETINGS la mostra nel field `👇 __**LA MODERAZIONE AGGIUNGE**__`; la narrativa principale non deve ripeterla inline. Eccezione: `inactive_tempban` (tempban automatico per inattività) non espone field moderazione.
