from datetime import datetime, timedelta, timezone

from app.services.qna_session_store import QnaSession, QnaSessionStore


def test_qna_session_store_ttl_expiry() -> None:
    store = QnaSessionStore(ttl_minutes=60)
    key = (1, 2, 3)
    session = QnaSession(scope="general_llm", history=[{"role": "user", "content": "ciao"}])
    session.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=61)
    store.set(key, session)
    store._sessions[key].last_used_at = datetime.now(timezone.utc) - timedelta(minutes=61)

    assert store.get(key) is None


def test_qna_session_store_touch_keeps_session_alive() -> None:
    store = QnaSessionStore(ttl_minutes=60)
    key = (1, 2, 4)
    session = QnaSession(scope="general_llm", history=[])
    store.set(key, session)
    previous = store._sessions[key].last_used_at

    store.touch(key)

    assert store._sessions[key].last_used_at >= previous
