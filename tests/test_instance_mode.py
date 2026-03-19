import pytest


@pytest.fixture
def bot_module(import_fresh):
    return import_fresh("app.core.bot")


def test_normalize_instance_mode(bot_module) -> None:
    assert bot_module.normalize_instance_mode("worker") == "worker"
    assert bot_module.normalize_instance_mode("worker1") == "worker"
    assert bot_module.normalize_instance_mode("worker2") == "worker"
    assert bot_module.normalize_instance_mode("main") == "main"
    assert bot_module.normalize_instance_mode("") == "main"
    assert bot_module.normalize_instance_mode(None) == "main"
