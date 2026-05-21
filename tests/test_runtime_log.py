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
