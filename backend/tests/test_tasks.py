from app.tasks.system import ping


def test_ping_task_logic() -> None:
    assert ping() == "pong"
