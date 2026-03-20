from __future__ import annotations


def describe_placeholders() -> str:
    return (
        "Placeholder: {user}, {username}, {display_name}, {mention}, {user_id}, {server}, {guild_id}, {days_inactive}, "
        "{window_days}, {min_messages}, {message_count}, {grace_days}, {reminder_count}, {ban_days}, {rejoin_link}, {reason}, "
        "{moderator}, {moderator_mention}, {duration}, {duration_days}, {expires_at}, {inactivity_text}."
    )
