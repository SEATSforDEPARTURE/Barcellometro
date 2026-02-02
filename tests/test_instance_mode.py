from app.core.bot import normalize_instance_mode


def test_normalize_instance_mode() -> None:
    assert normalize_instance_mode("worker") == "worker"
    assert normalize_instance_mode("worker1") == "worker"
    assert normalize_instance_mode("worker2") == "worker"
    assert normalize_instance_mode("main") == "main"
    assert normalize_instance_mode("") == "main"
    assert normalize_instance_mode(None) == "main"
