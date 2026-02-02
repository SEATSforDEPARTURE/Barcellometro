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

- Il bot **non registra nulla di default**: abilita ogni canale con `/barcellometro check on` prima di inviare messaggi da tracciare.
- Assicurati di attivare **Message Content Intent** e **Server Members Intent** nelle impostazioni del bot su Discord Developer Portal, altrimenti gli eventi messaggio e membro non arrivano.
- Per la traduzione locale serve installare i modelli Argos Translate (lingua sorgente → italiano).

## Comandi disponibili (solo guild)

### Abilitazione canali
- `/barcellometro check on` → abilita raccolta eventi nel canale.
- `/barcellometro check off` → disabilita raccolta eventi nel canale.

### Retention
- `/barcellometro retention get` → mostra i giorni correnti.
- `/barcellometro retention set days:<int>` → aggiorna la retention.

### Backfill
- `/barcellometro backfill on` → abilita il backfill e lo esegue subito.
- `/barcellometro backfill off` → disabilita il backfill.
- `/barcellometro backfill <giorni>` → aggiorna i giorni di backfill.

Il backfill verifica il gap tra l'ultimo evento registrato e l'ora attuale e recupera i messaggi mancanti
nei canali abilitati fino al limite di giorni configurato (default 30). Se il primo evento salvato è più
recente dell'inizio finestra, aggiunge anche il backfill per la porzione iniziale mancante. Se attivo,
parte automaticamente ad ogni riavvio del bot. I comandi manuali forzano una scansione completa della
finestra configurata in modo idempotente.

### Status
- `/status barcellometro` → stato generale bot/DB.
- `/status barcellometro service:<nome>` → stato servizio/plugin.

### AI centrale
- `/barcellometro ai on` → abilita il servizio AI.
- `/barcellometro ai off` → disabilita il servizio AI.
- `/barcellometro ai-model task:<task> model:<nome>` → imposta il modello AI per task (`summary`, `transcription`, `translation`).

### STT
- `/barcellometro stt backend local|ai`
- `/barcellometro stt model small|medium|large-v3`
- `/barcellometro stt compute int8|int8_float16|float16`
- `/barcellometro stt beam 1|3|5`
- `/barcellometro stt language it|auto`

### Translate
- `/barcellometro translate backend local|ai`
- `/barcellometro translate target it`

### Audio notes
- `/barcellometro audio_notes on`
- `/barcellometro audio_notes off`
- `/barcellometro audio_notes status`
- `/barcellometro audio_notes limits max_mb:<n> max_duration_s:<n> discord_max_chars:<n> queue_max:<n>`

Requisiti runtime: `ffmpeg` e `ffprobe` disponibili nel PATH (in alternativa viene usato il binario fornito da `imageio-ffmpeg`).

### Voice ingest
- `/barcellometro voice_ingest on bot:<bot> [voice_channel] [text_channel]` (default: chat del canale vocale)
- `/barcellometro voice_ingest off bot:<bot>`
- `/barcellometro voice_ingest join <voice_channel>`
- `/barcellometro voice_ingest leave`

### Policy ruoli/utenti
- `/barcellometro role set-role role:<ruolo> command:<cmd> usage_limit:<n> cooldown_seconds:<sec>`
- `/barcellometro role set-user user:<utente> command:<cmd> usage_limit:<n> cooldown_seconds:<sec>`
- `/barcellometro role clear-role role:<ruolo> command:<cmd>`
- `/barcellometro role clear-user user:<utente> command:<cmd>`
- `/barcellometro role show-role role:<ruolo>`
- `/barcellometro role show-user user:<utente>`

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
