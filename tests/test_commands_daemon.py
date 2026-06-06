from click.testing import CliRunner

from nudge.commands.daemon import daemon_command


def test_daemon_run_once_ignores_invalid_sleep_ms_env(monkeypatch):
    logged_start = {}

    monkeypatch.setenv("NUDGE_DAEMON_SLEEP_MS", "not-a-number")
    monkeypatch.setattr(
        "nudge.commands.daemon.recover_stale_running_commands",
        lambda *, stale_minutes, max_attempts: {"requeued_count": 0, "dead_lettered_count": 0},
    )
    monkeypatch.setattr("nudge.commands.daemon.claim_next_queued_command", lambda: None)
    monkeypatch.setattr(
        "nudge.commands.daemon._log_daemon_start",
        lambda **kwargs: logged_start.update(kwargs),
    )

    result = CliRunner().invoke(daemon_command, ["run", "--once"], prog_name="nudge daemon")

    assert result.exit_code == 0
    assert result.exception is None
    assert logged_start["sleep_ms"] == 3000
