from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def create_engine_and_session(db_url: str, echo: bool = False):
    engine = create_engine(db_url, echo=echo, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine, SessionLocal
