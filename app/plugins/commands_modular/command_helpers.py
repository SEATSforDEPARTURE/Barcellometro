from __future__ import annotations

import logging

import discord
from discord import app_commands


def add_group_once(parent: app_commands.Group, child: app_commands.Group, logger: logging.Logger) -> bool:
    existing_names = {cmd.name for cmd in parent.commands}
    if child.name in existing_names:
        logger.warning("Skipping duplicate subgroup %r under /%s", child.name, parent.qualified_name or parent.name)
        return False
    parent.add_command(child)
    return True


def add_command_once(group: app_commands.Group, command_obj: app_commands.Command, logger: logging.Logger) -> bool:
    existing_names = {cmd.name for cmd in group.commands}
    if command_obj.name in existing_names:
        logger.warning("Skipping duplicate command %r under /%s", command_obj.name, group.qualified_name or group.name)
        return False
    group.add_command(command_obj)
    return True


def describe_placeholders() -> str:
    return (
        "Placeholder: {user}, {username}, {display_name}, {user_id}, {server}, {guild_id}, {days_inactive}, "
        "{window_days}, {min_messages}, {message_count}, {grace_days}, {reminder_count}, {ban_days}, {rejoin_link}, {reason}."
    )
