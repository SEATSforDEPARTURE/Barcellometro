from __future__ import annotations

import logging

from discord import app_commands


def count_child_commands(parent: app_commands.Group) -> int:
    return len(parent.commands)


def _group_label(group: app_commands.Group) -> str:
    return group.qualified_name or group.name


def add_group_once(parent: app_commands.Group, child: app_commands.Group, logger: logging.Logger) -> bool:
    parent_label = _group_label(parent)
    current_children = count_child_commands(parent)
    logger.debug(
        "Attempting to register subgroup /%s under /%s (existing_children=%d)",
        child.name,
        parent_label,
        current_children,
    )
    existing_names = {cmd.name for cmd in parent.commands}
    if child.name in existing_names:
        logger.warning("Skipping duplicate subgroup %r under /%s", child.name, parent_label)
        return False
    try:
        parent.add_command(child)
    except ValueError:
        logger.exception(
            "Failed to register subgroup /%s under /%s (existing_children=%d).",
            child.name,
            parent_label,
            current_children,
        )
        raise
    return True


def add_command_once(group: app_commands.Group, command_obj: app_commands.Command, logger: logging.Logger) -> bool:
    group_label = _group_label(group)
    current_children = count_child_commands(group)
    logger.debug(
        "Attempting to register command /%s %s (existing_children=%d)",
        group_label,
        command_obj.name,
        current_children,
    )
    existing_names = {cmd.name for cmd in group.commands}
    if command_obj.name in existing_names:
        logger.warning("Skipping duplicate command %r under /%s", command_obj.name, group_label)
        return False
    try:
        group.add_command(command_obj)
    except ValueError:
        logger.exception(
            "Failed to register command %r under /%s (existing_children=%d).",
            command_obj.name,
            group_label,
            current_children,
        )
        raise
    return True
