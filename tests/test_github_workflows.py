from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_verify_workflow_runs_project_verification_entrypoint():
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")

    assert "scripts/verify.sh" in workflow
    assert "python-version: '3.12'" in workflow
    assert "npm ci" in workflow
    assert "working-directory: docs" in workflow
