from __future__ import annotations
import time
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from app.db.models.core import AuditLog

START_TIME = time.time()

def get_manifest():
    return {
        "name": "status",
        "version": "1.0.0",
        "description": "Diagnostica generale del sistema e stato per plugin",
        "services_required": ["settings", "db_health"],
        "services_optional": ["db_session_factory", "ai", "ai_client"],
        "tables_used": ["audit_log"],
        # opzionale: "healthcheck": callable(registry)->dict
    }

AI_SERVICE_KEYS = ("ai", "ai_client")

def _format_audit_entry(entry: AuditLog) -> str:
    ts = entry.created_at.isoformat(timespec="seconds") if entry.created_at else "?"
    return f"{ts} - {entry.action}"

def _load_recent_errors(session_factory, limit: int = 5) -> tuple[list[str], str | None]:
    if session_factory is None:
        return [], "n/d (db_session_factory assente)"

    try:
        with session_factory() as session:
            stmt = (
                select(AuditLog)
                .where(
                    (AuditLog.action.ilike("%error%")) | (AuditLog.action.ilike("%exception%"))
                )
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            if not rows:
                fallback = (
                    select(AuditLog)
                    .order_by(AuditLog.created_at.desc())
                    .limit(limit)
                )
                rows = session.execute(fallback).scalars().all()
            return [_format_audit_entry(row) for row in rows], None
    except Exception as e:
        return [], f"errore lettura audit_log: {e}"

def _ai_status(registry) -> tuple[bool, str]:
    available = [key for key in AI_SERVICE_KEYS if registry.has(key)]
    if available:
        return True, ", ".join(available)
    return False, "off"

class BarcellometroGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot, registry):
        super().__init__(name="barcellometro", description="Comandi del Barcellometro")
        self.bot = bot
        self.registry = registry

    @app_commands.command(name="status", description="Stato generale o di un plugin specifico")
    @app_commands.describe(plugin="Nome modulo plugin (es: riassunto_dm). Lascia vuoto per status generale.")
    async def status(self, interaction: discord.Interaction, plugin: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)

        db_health = self.registry.get("db_health")
        db_ok = False
        db_msg = "db_health non disponibile"
        if db_health is not None:
            try:
                db_ok, db_msg = db_health.ping()
            except Exception as e:
                db_ok = False
                db_msg = f"errore ping: {e}"
        uptime_s = int(time.time() - START_TIME)

        loaded = getattr(self.bot, "plugin_manifests", {}) or {}
        services = self.registry.list()

        if not plugin:
            ai_on, ai_detail = _ai_status(self.registry)
            session_factory = self.registry.get("db_session_factory")
            recent_errors, errors_msg = _load_recent_errors(session_factory)

            errors_line = "• Ultimi errori: (nessuno)"
            if errors_msg:
                errors_line = f"• Ultimi errori: {errors_msg}"
            elif recent_errors:
                errors_line = "• Ultimi errori:\n" + "\n".join(f"  - {entry}" for entry in recent_errors)

            lines = [
                "🟢 **Barcellometro online**",
                f"• Uptime: {uptime_s}s",
                f"• DB: {'✅' if db_ok else '❌'} {db_msg}",
                f"• AI: {'✅' if ai_on else '❌'} {ai_detail}",
                f"• Plugin caricati: {', '.join(sorted(loaded.keys())) if loaded else '(nessuno)'}",
                f"• Servizi: {', '.join(services)}",
                errors_line,
            ]
            errs = [k for k,v in loaded.items() if isinstance(v, dict) and v.get('error')]
            if errs:
                lines.append(f"• Plugin con errori: {', '.join(errs)}")
            await interaction.followup.send("\n".join(lines), ephemeral=True)
            return

        key = plugin.strip().lower()
        manifest = loaded.get(key)
        if not manifest:
            await interaction.followup.send(
                f"⚠️ Plugin '{key}' non trovato tra i caricati.\n"
                f"Caricati: {', '.join(sorted(loaded.keys())) if loaded else '(nessuno)'}",
                ephemeral=True,
            )
            return

        req = manifest.get("services_required", []) if isinstance(manifest, dict) else []
        opt = manifest.get("services_optional", []) if isinstance(manifest, dict) else []
        missing_req = [s for s in req if not self.registry.has(s)]
        present_req = [s for s in req if self.registry.has(s)]
        present_opt = [s for s in opt if self.registry.has(s)]
        missing_opt = [s for s in opt if not self.registry.has(s)]

        header = f"🔎 **Status plugin: {key}**"
        meta = f"• Versione: {manifest.get('version','?')}\n• Descrizione: {manifest.get('description','')}"
        load_state = "• Load: ✅ ok" if not manifest.get("error") else f"• Load: ❌ errore\n• Errore: {manifest.get('error')}"
        deps = (
            f"• Servizi richiesti OK: {', '.join(present_req) if present_req else '(nessuno)'}\n"
            f"• Servizi richiesti MANCANTI: {', '.join(missing_req) if missing_req else '(nessuno)'}\n"
            f"• Servizi opzionali OK: {', '.join(present_opt) if present_opt else '(nessuno)'}\n"
            f"• Servizi opzionali mancanti: {', '.join(missing_opt) if missing_opt else '(nessuno)'}"
        )

        extra = ""
        hc = manifest.get("healthcheck")
        if callable(hc):
            try:
                res = hc(self.registry)
                if isinstance(res, dict) and res:
                    extra = "• Dettagli:\n" + "\n".join([f"  - {k}: {v}" for k,v in res.items()])
            except Exception as e:
                extra = f"• Healthcheck plugin: ❌ {e}"

        msg = "\n".join([header, meta, load_state, deps, extra]).strip()
        await interaction.followup.send(msg, ephemeral=True)

def setup(bot: commands.Bot, registry):
    bot.tree.add_command(BarcellometroGroup(bot, registry))
