# Barcellometro

Bot Discord modulare in Python con architettura future-proof basata su service registry + plugin loader.

## Setup

1. Crea un venv e installa le dipendenze:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copia `.env.example` in `.env` e compila i valori:

```bash
cp .env.example .env
```

3. Prepara i config file-based in `settings/` copiando i template che vuoi personalizzare:

```bash
cp settings/entitlements.example.json settings/entitlements.json
cp settings/greetings_trigger.example.json settings/greetings_trigger.json
cp settings/aura_rules.example.json settings/aura_rules.json
cp settings/aura_archetypes.example.json settings/aura_archetypes.json
cp settings/aura_missions.example.json settings/aura_missions.json
cp settings/barcello_trigger.example.json settings/barcello_trigger.json
```

Per i dettagli operativi sui config centralizzati vedi `settings/README.md`.

- `DISCORD_TOKEN`: token del bot.
- `GUILD_ID`: ID della guild su cui sincronizzare i comandi.
- `DB_PATH`: path del database SQLite (default `bot.sqlite`).
- `DEFAULT_RETENTION_DAYS`: giorni di retention iniziali.
- `IGNORE_BOTS`: ignora messaggi bot.
- `LOG_LEVEL`: livello di logging.
- `OPENAI_API_KEY`: chiave API OpenAI (opzionale, solo per AI).
- `INSTANCE_MODE`: modalità istanza (`main`, `worker`, `worker1`, `worker2`, ...).
- `PLUGIN_ALLOWLIST`: lista plugin separata da virgole da caricare (opzionale).
- `STT_LOCAL_MODEL`: modello locale (default `small`).
- `STT_LOCAL_COMPUTE_TYPE`: compute type locale (`int8`, `int8_float16`, `float16`).
- `STT_LOCAL_BEAM_SIZE`: beam size locale (default `1`).
- `AUDIO_NOTES_MAX_MB`: dimensione massima audio (MB).
- `AUDIO_NOTES_MAX_DURATION_S`: durata massima audio (secondi).
- `AUDIO_NOTES_DISCORD_MAX_CHARS`: max caratteri per messaggio trascritto.
- `AUDIO_NOTES_QUEUE_MAX`: massimo numero note vocali in coda.
- `VOICE_INGEST_ENABLED`: abilita ingest vocale (default false).
- `VOICE_INGEST_DEFAULT_CHUNK_SECONDS`: durata chunk STT (secondi).
- `VOICE_INGEST_MIN_CHARS`: minimo caratteri trascritti per salvare.
- `VOICE_INGEST_MAX_QUEUE`: dimensione coda globale ingest.
- `VOICE_INGEST_MAX_QUEUE_PER_USER`: max chunk in coda per utente.
- `VOICE_INGEST_RATE_LIMIT_USER_PER_MIN`: rate limit chunk per utente/min.
- `VOICE_INGEST_MAX_CONCURRENT_STT`: concorrenza STT.
- `VOICE_INGEST_STT_TIMEOUT_SEC`: timeout STT (secondi).
- `VOICE_INGEST_CIRCUIT_BREAKER_FAILS`: soglia errori STT.
- `VOICE_INGEST_CIRCUIT_BREAKER_COOLDOWN_SEC`: cooldown breaker (secondi).

## Run

```bash
python -m app.main
```

## Note importanti

- Il bot **non registra nulla di default**: abilita ogni canale con `/admin events on` prima di inviare messaggi da tracciare.
- Assicurati di attivare **Message Content Intent** e **Server Members Intent** nelle impostazioni del bot su Discord Developer Portal, altrimenti gli eventi messaggio e membro non arrivano.
- Per la traduzione locale serve installare i modelli Argos Translate (lingua sorgente → italiano).

## Comandi disponibili (solo guild)

### Impostazioni DB (opzionali)
- `messages_quiet_enabled`: `1`/`0` per attivare/disattivare le quiet hours (default 1).
- `messages_quiet_start` / `messages_quiet_end`: quiet hours (HH:MM Europe/Rome) per messaggi community (default 01:00–08:30).
- `messages_daily_cap_enabled`: `1`/`0` per attivare/disattivare il cap giornaliero (default 1).
- `messages_daily_cap`: limite invii/giorno per canale per messaggi community (default 6).

### Abilitazione canali
- `/admin events on` → abilita raccolta eventi nel canale.
- `/admin events off` → disabilita raccolta eventi nel canale.

### Retention
- `/admin retention status` → mostra i giorni correnti.
- `/admin retention config_set days:<int>` → aggiorna la retention.

### Backfill
- `/admin backfill on` → abilita il backfill e lo esegue subito.
- `/admin backfill off` → disabilita il backfill.
- `/admin backfill config_set days:<giorni>` → aggiorna i giorni di backfill.

Il backfill verifica il gap tra l'ultimo evento registrato e l'ora attuale e recupera i messaggi mancanti
nei canali abilitati fino al limite di giorni configurato (default 30). Se il primo evento salvato è più
recente dell'inizio finestra, aggiunge anche il backfill per la porzione iniziale mancante. Se attivo,
parte automaticamente ad ogni riavvio del bot. I comandi manuali forzano una scansione completa della
finestra configurata in modo idempotente.

### Status
- `/admin status` → stato generale bot/DB.
- `/admin status service:<nome>` → stato servizio/plugin.

### Rendering embed centralizzato
- `/embed footer on|off|status` → amministrazione canonica del dominio footer.
- `/embed footer template_global_set|show|reset` → template globale footer.
- `/embed footer template_service_set|show|reset service:<nome>` → override footer per servizio con autocomplete basato su **servizi top-level pubblici che producono embed visibili** (`audio`, `triggers`, `greetings`, `channelsummary`, `serversummary`, `dmchannelsummary`, `dmserversummary`, `campaigns`, `qna`, `inactivity`, `embed`, `commandguard`, `database`, `status`, `ai`), con alias tecnici gestiti internamente.
- `/embed author on|off|status` → amministrazione canonica del dominio author.
- `/embed author template_global_set|show|reset` → template globale author.
- `/embed author template_service_set|show|reset service:<nome>` → override author per servizio con la stessa source of truth top-level condivisa con footer/images/description.

Regole body ufficiali (single source of truth):
- AUTHOR: `servizio NOME CANONICO INGLESE TOP-LEVEL` (o `· Pag. X/Y` per multipagina);
- titolo embed: `(emoji) __**TITOLO**__` (sempre MAIUSCOLO, grassetto, sottolineato);
- description: solo introduzione breve in corsivo, senza emoji iniziale;
- titolo field: `(emoji) __**TITOLO FIELD**__` (sempre MAIUSCOLO, grassetto, sottolineato);
- sezioni importanti (`TEMI`, `MOMENTI SALIENTI`, `CLASSIFICA`, `MISSIONI`, `CONSIGLI`) sempre come `fields` reali;
- usare sempre `format_standard_title(...)`, `format_standard_field_name(...)`, `format_standard_description(...)`;
- vietate costruzioni manuali incoerenti (`📈 Trend`, `📓 RESOCONTO CANALE`, `📈 __**Trend**__`, `📈 **PANORAMICA**` in description, `👇 **Risposta:**` in description quando strutturale).

Regole operative:
- `footer` e `author` sono domini distinti ma centralizzati;
- il footer controlla brand/versione/frase/contributor tecnici;
- l'author controlla l'intestazione visuale del servizio;
- la precedenza documentale e runtime è `override servizio > globale > fallback`;
- il fallback author per servizio è `emoji servizio + nome servizio`;
- gli status `/embed ... status` usano vista multipagina quando l'elenco servizi è lungo.

### AI centrale
- `/barcello [user1] [user2] [minuti]` → report user-facing del barcello inviato in DM con conferma standardizzata nel canale.
- `/admin ai on` → abilita il servizio AI.
- `/admin ai off` → disabilita il servizio AI.
- `/admin ai model_set task:<task> model:<nome>` → imposta il modello AI per task (`summary`, `server_summary`, `audio_summary`, `qa`, `analysis`, `transcription`, `translation`).
- `/admin barcello run [user1] [user2] [window_minutes]` → esegue lo stesso report barcello dal namespace admin senza rimuovere i comandi di configurazione.
- `/admin barcello calibrate` → calibra i pesi del motore barcello (mod).

### STT
- `/audio clips stt_set backend:local|ai`
- `/audio clips stt_set model:small|medium|large-v3`
- `/audio clips stt_set compute:int8|int8_float16|float16`
- `/audio clips stt_set beam:1|3|5`
- `/audio clips stt_set language:it|auto`

### Translate
- `/audio clips translate_set backend:local|ai`
- `/audio clips translate_set target:it`

### Audio notes
- `/audio on`
- `/audio off`
- `/audio status`
- `/audio clips limits_set max_mb:<n> max_duration_s:<n> discord_max_chars:<n> queue_max:<n>`

Requisiti runtime: `ffmpeg` e `ffprobe` disponibili nel PATH (in alternativa viene usato il binario fornito da `imageio-ffmpeg`).

### Voice ingest
- `/admin voice_ingest join <voice_channel>`
- `/admin voice_ingest leave`
- `/privacy on [voice_channel]`
- `/privacy off [voice_channel]`
- `/privacy status [voice_channel]`

### Users / moderation
- `/users kick user:<utente> [reason:<testo>]`
- `/users kick_list`
- `/users ban user:<utente> [reason:<testo>]`
- `/users ban_list`
- `/users tempban user:<utente> duration:<durata> [reason:<testo>]`
- `/users tempban_list`
- `/users grace user:<utente> duration:<durata> [reason:<testo>]`
- `/users grace_list`
- `/users unban nick_or_id:<ultimo_nick_o_id_utente> [reason:<testo>]`
- `/users untempban nick_or_id:<ultimo_nick_o_id_utente> [reason:<testo>]`
- `/users ungrace nick_or_id:<ultimo_nick_o_id_utente> [reason:<testo>]`
- Alias top-level: `/kick`, `/ban`, `/tempban`, `/grace` → alias reali dei corrispondenti `/users ...`.

### Greetings / inactivity
- `/greetings on [channel]`
- `/greetings off`
- `/greetings status`
- `/greetings notify_set channel:<canale>`
- `/greetings notify_show`
- `/greetings notify_reset`
- `/greetings user_card on|off|status`
- `template_set/show/reset` non esistono più nel contratto `greetings`; l'editorialità resta demandata alla source of truth `settings/greetings_trigger.json`.
- `/inactivity on|off|status`
- `/inactivity autokick on|off|status`
- `/inactivity grace on|off|status|limits_set|limits_show|limits_reset`
- `/inactivity tempban on|off|status|limits_set|limits_show|limits_reset`
- `/inactivity dms template_reminder_set|template_reminder_show|template_reminder_reset`
- `/inactivity dms cooldown_set|cooldown_show|cooldown_reset`
- `/inactivity dms invite_set|invite_show|invite_reset`
- `/inactivity policy default_set|default_show|default_reset`
- `/inactivity policy role_set|role_show|role_reset`
- `/inactivity policy exceptions_add|exceptions_remove|exceptions_show|exceptions_list`
- `/inactivity run`

### Campagne community
- `/campagne on` → abilita invii automatici nel canale corrente.
- `/campagne off` → disabilita nel canale corrente.
- `/campagne status` → stato canale + conteggio campagne.
- `/campagne aggiungi testo:"..." ogni_minuti:<int> ora_inizio:"HH:MM" [testo_verde:"..."] [testo_giallo:"..."] [testo_rosso:"..."] [testo_nero:"..."] [mood_mode:<AUTO|IGNORE_BARCELLO|GREEN_ONLY|YELLOW_ONLY|RED_ONLY|BLACK_ONLY>] [jitter_sec:<int>] [solo_se_inattivo_min:<int>]`
- `/campagne quiet_status|quiet_on|quiet_off|quiet_set start:"HH:MM" end:"HH:MM"` → gestione quiet hours.
- `/campagne cap_status|cap_on|cap_off|cap_set n:<int>` → gestione cap giornaliero.
- `/campagne lista` → elenco campagne con ID reali.
- `/campagne cancella id:<int>` → soft delete.
- `/campagne pausa id:<int>` → disabilita.
- `/campagne riprendi id:<int>` → abilita + ricalcolo next_run.
- `/campagne test id:<int>` → invio immediato nel canale corrente.
- `/campagne prompt on|off|status|create|list|delete|test` → gestione campagne AI prompt.


### QnA
- `/qna on`
- `/qna off`
- `/qna status`
- `/qna limits_show`
- `/qna limits_set tier_key:<base|role1|role2|role3|mod> limit_int:<int>`
- `/qna bonus_add user:<utente> amount_int:<int> [hours_valid:<int>]`
- `/qna bonus_clear user:<utente>`
- `/qna bonus_show user:<utente>`

### Insights
- `/insights on`
- `/insights off`
- `/insights status`
- `/insights config testo:"..."`

### Riassunto
- `/riassunto ultimi <quantità> <minuti|ore|giorni|settimane>`
- `/riassunto oggi`
- `/riassunto ieri`
- `/riassunto range da:<DD/MM/YYYY HH:MM> a:<DD/MM/YYYY HH:MM>`

#### Configurazione `/riassunto`
Il comando legge il JSON da `summary.config` (settings). Esempio di default:

```json
{
  "tiers": {
    "role1": { "label": "PLUS", "sections": ["themes", "moments", "notes"] },
    "role2": { "label": "PRO", "sections": ["themes", "moments", "quotes", "notes"] },
    "role3": { "label": "PRO MAX", "sections": ["themes", "moments", "quotes", "dynamics"] },
    "mod": { "label": "MOD", "sections": ["themes", "moments", "quotes", "dynamics", "impact", "advice", "metrics", "ai"] }
  },
  "ai_enabled_tiers": ["role2", "role3", "mod"],
  "fallback_local": true,
  "evidence_mode": { "links_off": 2, "links_on": 4, "mod_explain_links": 3 },
  "include_names_when_score": { "default": "green_only", "mod": "always" },
  "max_messages": 600
}
```

### Policy ruoli/utenti
- `/admin commandguard role_add role:<ruolo> command:<cmd> usage_limit:<n> cooldown_seconds:<sec>`
- `/admin commandguard user_add user:<utente> command:<cmd> usage_limit:<n> cooldown_seconds:<sec>`
- `/admin commandguard role_remove role:<ruolo> command:<cmd>`
- `/admin commandguard user_remove user:<utente> command:<cmd>`
- `/admin commandguard role_show role:<ruolo>`
- `/admin commandguard user_show user:<utente>`

Se non esiste alcuna policy, i comandi sono accessibili solo agli admin. Le policy utente hanno priorità
su quelle di ruolo. I limiti e cooldown vengono conteggiati e sono disponibili ai plugin che li richiedono.

## Validator architetturali

Per validare i residui legacy post-refactor e ottenere un report console con `OK`, `WARNING` ed `ERROR`:

```bash
python scripts/validate_architecture_residues.py
```

Lo script termina con exit code diverso da zero solo in presenza di violazioni reali; gli shim legacy temporanei documentati restano visibili come warning.

Per verificare gli standard embed e bloccare messaggi raw / helper duplicati / embed senza footer meta:

```bash
python validate_embed_standards.py
```

Il validator stampa un report per file e termina con exit code diverso da zero se trova violazioni. È anche eseguito nella suite Pytest tramite `tests/test_embed_standards_validator.py`.

## Verifica DB

Esempi di query:

```bash
sqlite3 bot.sqlite "SELECT COUNT(*) FROM messages;"
sqlite3 bot.sqlite "SELECT channel_id, enabled FROM channels;"
sqlite3 bot.sqlite "SELECT * FROM events ORDER BY ts DESC LIMIT 5;"
```

## Architettura

Struttura canonica del progetto:

- `settings/`: template e override dei config file-based versionati/locali.
- `app/services/`: servizi runtime applicativi.
- `app/renderers/`: renderer e composizione output/embed.
- `app/utils/`: utility e compatibility helpers mirati.
- `app/plugins/commands_modular/`: moduli slash commands e relativo wiring.

Note di compatibilità:

- `app/settings/...` può ancora comparire solo come path legacy di compatibilità runtime; non è documentato come struttura canonica e non va usato per nuovi setup.
- `app/features/` non fa parte del layout finale e non deve essere reintrodotto.

Check utili:

- `python -m scripts.validate_commands`: valida la slash tree, segnala naming/triadi/descrizioni fuori standard e può rigenerare `docs/command_tree_report.md`.
- `python -m scripts.validate_project_layout`: valida il layout finale e blocca riferimenti strutturali legacy non consentiti.
