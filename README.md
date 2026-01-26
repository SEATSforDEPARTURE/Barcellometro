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

## Run

```bash
python -m app.main
```

## Note importanti

- Il bot **non registra nulla di default**: abilita ogni canale con `/barcellometro check on` prima di inviare messaggi da tracciare.
- Assicurati di attivare **Message Content Intent** e **Server Members Intent** nelle impostazioni del bot su Discord Developer Portal, altrimenti gli eventi messaggio e membro non arrivano.

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
- `app/services`: DatabaseService, IngestService, RetentionService, BackfillService, CommandGuardService, StatusService.
- `app/plugins`: adapter Discord (eventi), comandi slash, consumer di esempio.
