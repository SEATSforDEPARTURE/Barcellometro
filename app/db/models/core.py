from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, Float, String, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models.meta import Base

class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(32), default="system")
    action: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TextIngestChannelConfig(Base):
    __tablename__ = "text_ingest_channel_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    channel_id: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=10)
    backfill_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backfill_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TextIngestMessage(Base):
    __tablename__ = "text_ingest_message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    channel_id: Mapped[str] = mapped_column(String(32), index=True)
    message_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    author_id: Mapped[str] = mapped_column(String(32), index=True)
    author_nickname: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    roles_json: Mapped[str] = mapped_column(Text, default="[]")
    write_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    write_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_since_last_message: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relationships_json: Mapped[str] = mapped_column(Text, default="{}")
