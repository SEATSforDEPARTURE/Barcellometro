from __future__ import annotations
from sqlalchemy import text

class DBHealthService:
    def __init__(self, engine):
        self.engine = engine

    def ping(self) -> tuple[bool, str]:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, "ok"
        except Exception as e:
            return False, str(e)
