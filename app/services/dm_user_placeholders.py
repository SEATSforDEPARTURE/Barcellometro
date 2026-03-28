from __future__ import annotations

from typing import Any


def build_user_placeholder_payload(user: Any) -> dict[str, str]:
    user_id = str(getattr(user, "id", "") or "")
    mention = str(getattr(user, "mention", "") or "").strip() or (f"<@{user_id}>" if user_id else "")
    username = str(getattr(user, "name", "") or "")
    display_name = str(getattr(user, "display_name", "") or username)
    return {
        "mention": mention,
        "user": mention,
        "username": username,
        "display_name": display_name,
        "user_id": user_id,
    }
