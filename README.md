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

## Comandi disponibili (solo guild)

### Abilitazione canali
- `/barcellometro check on` → abilita raccolta eventi nel canale.
- `/barcellometro check off` → disabilita raccolta eventi nel canale.

### Retention
- `/barcellometro retention get` → mostra i giorni correnti.
- `/barcellometro retention set days:<int>` → aggiorna la retention.

### Status
- `/status barcellometro` → stato generale bot/DB.
- `/status barcellometro service:<nome>` → stato servizio/plugin.

## Verifica DB

Esempi di query:

```bash
sqlite3 bot.sqlite "SELECT COUNT(*) FROM messages;"
sqlite3 bot.sqlite "SELECT channel_id, enabled FROM channels;"
sqlite3 bot.sqlite "SELECT * FROM events ORDER BY ts DESC LIMIT 5;"
```

## Architettura

- `app/core`: config, logging, ServiceRegistry, PluginLoader, entrypoint.
- `app/services`: DatabaseService, IngestService, RetentionService, StatusService.
- `app/plugins`: adapter Discord (eventi), comandi slash, consumer di esempio.
