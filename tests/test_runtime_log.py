import json

from nudge.errors import ErrorReport
from nudge.runtime_log import log_doctor_checks, log_error_report, log_warning, runtime_log_path


def test_runtime_log_writes_warning_to_configured_state_dir(tmp_path):
    config = {"state": {"dir": str(tmp_path)}}

    path = log_warning("test", "Something needs attention", hint="Fix it", config=config)

    assert path == tmp_path / "logs" / "nudge-runtime.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["level"] == "WARN"
    assert entry["source"] == "test"
    assert entry["message"] == "Something needs attention"
    assert entry["hint"] == "Fix it"


def test_runtime_log_records_error_report_without_raw_error(tmp_path):
    config = {"state": {"dir": str(tmp_path)}}
    error = ErrorReport(
        code="TEST_ERROR",
        title="Broken",
        detail="Repairable failure",
        next_steps=("Run doctor",),
        raw_error="raw provider output",
    )

    path = log_error_report("unit", error, config=config)

    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["level"] == "ERROR"
    assert entry["code"] == "TEST_ERROR"
    assert entry["next_steps"] == ["Run doctor"]
    assert "raw_error" not in entry


def test_doctor_check_logging_ignores_passes(tmp_path):
    config = {"state": {"dir": str(tmp_path)}}

    class Check:
        def __init__(self, status, name):
            self.status = status
            self.name = name
            self.message = f"{name} message"
            self.hint = f"{name} hint"

    path = log_doctor_checks(
        [Check("PASS", "Config"), Check("WARN", "Clock"), Check("FAIL", "LLM")],
        config=config,
    )

    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [entry["level"] for entry in entries] == ["WARN", "ERROR"]
    assert [entry["source"] for entry in entries] == ["doctor.Clock", "doctor.LLM"]


def test_runtime_log_path_uses_state_dir(tmp_path):
    assert runtime_log_path({"state": {"dir": str(tmp_path)}}) == tmp_path / "logs" / "nudge-runtime.jsonl"


def test_runtime_log_rotates_before_writing_when_size_exceeds_limit(tmp_path):
    config = {"state": {"dir": str(tmp_path)}, "runtime_log": {"max_bytes": 10}}
    path = runtime_log_path(config)
    path.parent.mkdir(parents=True)
    old_log = "x" * 10 + "\n"
    path.write_text(old_log, encoding="utf-8")

    log_warning("test", "rotated", config=config)

    assert (path.with_name("nudge-runtime.jsonl.1")).read_text(encoding="utf-8") == old_log
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert entries[0]["message"] == "rotated"


def test_runtime_log_keeps_at_most_three_rotated_files(tmp_path):
    config = {"state": {"dir": str(tmp_path)}, "runtime_log": {"max_bytes": 1}}
    path = runtime_log_path(config)
    path.parent.mkdir(parents=True)
    path.write_text("current\n", encoding="utf-8")
    path.with_name("nudge-runtime.jsonl.1").write_text("first\n", encoding="utf-8")
    path.with_name("nudge-runtime.jsonl.2").write_text("second\n", encoding="utf-8")
    path.with_name("nudge-runtime.jsonl.3").write_text("third\n", encoding="utf-8")

    log_warning("test", "new current", config=config)

    assert path.with_name("nudge-runtime.jsonl.1").read_text(encoding="utf-8") == "current\n"
    assert path.with_name("nudge-runtime.jsonl.2").read_text(encoding="utf-8") == "first\n"
    assert path.with_name("nudge-runtime.jsonl.3").read_text(encoding="utf-8") == "second\n"
    assert not path.with_name("nudge-runtime.jsonl.4").exists()


def test_runtime_log_does_not_rotate_when_size_is_within_limit(tmp_path):
    config = {"state": {"dir": str(tmp_path)}, "runtime_log": {"max_bytes": 10}}
    path = runtime_log_path(config)
    path.parent.mkdir(parents=True)
    path.write_text("x" * 9 + "\n", encoding="utf-8")

    log_warning("test", "same file", config=config)

    assert not path.with_name("nudge-runtime.jsonl.1").exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "x" * 9
    assert json.loads(lines[1])["message"] == "same file"


def test_runtime_log_rotation_uses_configured_state_dir(tmp_path):
    state_dir = tmp_path / "custom-state"
    config = {"state": {"dir": str(state_dir)}, "runtime_log": {"max_bytes": 1}}
    path = runtime_log_path(config)
    path.parent.mkdir(parents=True)
    path.write_text("old\n", encoding="utf-8")

    log_warning("test", "custom state", config=config)

    assert path == state_dir / "logs" / "nudge-runtime.jsonl"
    assert (state_dir / "logs" / "nudge-runtime.jsonl.1").read_text(encoding="utf-8") == "old\n"
