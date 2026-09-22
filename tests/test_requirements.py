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


def test_runtime_requirements_cover_third_party_imports():
    """公开运行依赖必须覆盖 nudge 包实际 import 的第三方包。"""
    runtime = {name.lower() for name in _reqs("requirements.txt")}
    assert "defusedxml" in runtime
    assert "pyyaml" in runtime
    assert "click" in runtime


def test_public_requirements_exclude_site_only_dependencies():
    """playwright 只用于私有 fork 的静态站点测试，不属于公开运行/开发依赖。"""
    for path in ("requirements.txt", "requirements-dev.txt"):
        assert "playwright" not in {name.lower() for name in _reqs(path)}
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "playwright" not in pyproject


def test_dev_requirements_cover_packaging_checks():
    """scripts/verify.sh 会调用 scripts/check_package.sh，需要打包工具链。"""
    dev = {name.lower() for name in _reqs("requirements-dev.txt")}
    assert {"build", "setuptools", "wheel"} <= dev


def test_pyproject_dependencies_match_runtime_requirements():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    declared = {
        line.strip().strip(',').strip('"').lower()
        for line in block.splitlines()
        if line.strip().strip(',').strip('"')
    }
    assert declared == {name.lower() for name in _reqs("requirements.txt")}
