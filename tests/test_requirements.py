from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _reqs(path: str) -> set[str]:
    lines = []
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#") and not clean.startswith("-r "):
            lines.append(clean.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0])
    return set(lines)


def test_runtime_requirements_do_not_include_pytest():
    assert "pytest" not in _reqs("requirements.txt")


def test_dev_requirements_include_pytest_and_runtime_requirements():
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in text
    assert "pytest" in _reqs("requirements-dev.txt")
