# Barcellometro — Base Core Intoccabile (v0.1.0)

Base del Barcellometro: **core intoccabile**, **plugin loader**, e comando **/barcellometro status** con parametro `plugin` (compatibile con plugin futuri).

## Setup rapido (Ubuntu 22.04)
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd barcellometro_base
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install .
cp .env.example .env
nano .env   # inserisci DISCORD_TOKEN, opzionale GUILD_ID
python -m scripts.run_bot
```

## Status
- `/barcellometro status` → stato generale
- `/barcellometro status plugin:<nome>` → drill-down di un plugin (anche futuro)

## Plugin system
Un plugin è un modulo in `app/plugins/<nome>.py` che espone:
- `setup(bot, registry)`
- `get_manifest()` (dict)

Caricamento: `PLUGINS` nel `.env` (CSV). Il plugin `status` viene sempre caricato.

## Database
SQLite via SQLAlchemy. In fase 0 crea le tabelle minime automaticamente (dev-friendly).
