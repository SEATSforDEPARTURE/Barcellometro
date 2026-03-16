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

- Il bot **non registra nulla di default**: abilita ogni canale con `/bm check on` prima di inviare messaggi da tracciare.
- Assicurati di attivare **Message Content Intent** e **Server Members Intent** nelle impostazioni del bot su Discord Developer Portal, altrimenti gli eventi messaggio e membro non arrivano.
- Per la traduzione locale serve installare i modelli Argos Translate (lingua sorgente → italiano).

## Comandi disponibili (solo guild)

### Impostazioni DB (opzionali)
- `messages_quiet_enabled`: `1`/`0` per attivare/disattivare le quiet hours (default 1).
- `messages_quiet_start` / `messages_quiet_end`: quiet hours (HH:MM Europe/Rome) per messaggi community (default 01:00–08:30).
- `messages_daily_cap_enabled`: `1`/`0` per attivare/disattivare il cap giornaliero (default 1).
- `messages_daily_cap`: limite invii/giorno per canale per messaggi community (default 6).

### Abilitazione canali
- `/bm check on` → abilita raccolta eventi nel canale.
- `/bm check off` → disabilita raccolta eventi nel canale.

### Retention
- `/bm retention get` → mostra i giorni correnti.
- `/bm retention set days:<int>` → aggiorna la retention.

### Backfill
- `/bm backfill on` → abilita il backfill e lo esegue subito.
- `/bm backfill off` → disabilita il backfill.
- `/bm backfill <giorni>` → aggiorna i giorni di backfill.

Il backfill verifica il gap tra l'ultimo evento registrato e l'ora attuale e recupera i messaggi mancanti
nei canali abilitati fino al limite di giorni configurato (default 30). Se il primo evento salvato è più
recente dell'inizio finestra, aggiunge anche il backfill per la porzione iniziale mancante. Se attivo,
parte automaticamente ad ogni riavvio del bot. I comandi manuali forzano una scansione completa della
finestra configurata in modo idempotente.

### Status
- `/status bm` → stato generale bot/DB.
- `/status bm service:<nome>` → stato servizio/plugin.

### AI centrale
- `/bm ai on` → abilita il servizio AI.
- `/bm ai off` → disabilita il servizio AI.
- `/bm ai-model task:<task> model:<nome>` → imposta il modello AI per task (`summary`, `server_summary`, `audio_summary`, `qa`, `analysis`, `transcription`, `translation`).
- `/bm barcello calibrate` → calibra i pesi del motore barcello (mod).

### STT
- `/bm stt backend local|ai`
- `/bm stt model small|medium|large-v3`
- `/bm stt compute int8|int8_float16|float16`
- `/bm stt beam 1|3|5`
- `/bm stt language it|auto`

### Translate
- `/bm translate backend local|ai`
- `/bm translate target it`

### Audio notes
- `/bm audio_notes on`
- `/bm audio_notes off`
- `/bm audio_notes status`
- `/bm audio_notes limits max_mb:<n> max_duration_s:<n> discord_max_chars:<n> queue_max:<n>`

Requisiti runtime: `ffmpeg` e `ffprobe` disponibili nel PATH (in alternativa viene usato il binario fornito da `imageio-ffmpeg`).

### Voice ingest
- `/bm voice_ingest join <voice_channel>`
- `/bm voice_ingest leave`
- `/privacy on [voice_channel]`
- `/privacy off [voice_channel]`
- `/privacy status [voice_channel]`

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
- `/bm role set-role role:<ruolo> command:<cmd> usage_limit:<n> cooldown_seconds:<sec>`
- `/bm role set-user user:<utente> command:<cmd> usage_limit:<n> cooldown_seconds:<sec>`
- `/bm role clear-role role:<ruolo> command:<cmd>`
- `/bm role clear-user user:<utente> command:<cmd>`
- `/bm role show-role role:<ruolo>`
- `/bm role show-user user:<utente>`

Se non esiste alcuna policy, i comandi sono accessibili solo agli admin. Le policy utente hanno priorità
su quelle di ruolo. I limiti e cooldown vengono conteggiati e sono disponibili ai plugin che li richiedono.

## Verifica DB

Esempi di query:

```bash
sqlite3 bot.sqlite "SELECT COUNT(*) FROM messages;"
sqlite3 bot.sqlite "SELECT channel_id, enabled FROM channels;"
sqlite3 bot.sqlite "SELECT * FROM events ORDER BY ts DESC LIMIT 5;"
```

## Architettura

- `app/core`: config, logging, ServiceRegistry, PluginLoader, entrypoint.
- `app/services`: DatabaseService, IngestService, RetentionService, BackfillService, CommandGuardService, AiService, STT/Translate services, StatusService.
- `app/plugins`: adapter Discord (eventi), comandi slash, consumer di esempio.
