# Release checklist

This project is prepared for PyPI packaging, but maintainers must still run the release manually. Do not upload artifacts, create GitHub releases, push tags, or publish Homebrew formulae until the checklist below is complete and the version is intentionally released.

## Scope and safety boundaries

- Package name: `nudge-ai-life-coach`.
- Console script: `nudge`.
- Required package data: `nudge/apple/*.swift` and `nudge/skills/builtins/*.yaml`.
- Public packages must not include tests, private config, local SQLite databases, Apple Health exports, `.env`, or other local state.
- API tokens are supplied by the operator's local PyPI/TestPyPI configuration; never commit tokens or paste them into docs, logs, issues, or release notes.

## Local preflight

1. Confirm the release commit is clean and reviewed:
   ```bash
   git status --short
   ```
2. Confirm the version in `pyproject.toml` and `CHANGELOG.md` match the intended release.
3. Run the full project verification entrypoint:
   ```bash
   scripts/verify.sh
   ```
   This includes tests, compile checks, CLI smoke checks, docs audit, and offline packaging checks.
4. If you only need to recheck package artifacts, run:
   ```bash
   scripts/check_package.sh
   ```
   The script builds wheel/sdist with `python -m build --no-isolation`, inspects contents locally, and does not upload or require credentials. If the Python `build` module is missing, install it in your development environment and rerun the script.

## Build artifacts

`dist/` should contain exactly one wheel and one source distribution for the target version:

```bash
ls -lh dist/
python - <<'PY'
from pathlib import Path
print('\n'.join(p.name for p in sorted(Path('dist').iterdir())))
PY
```

Inspect metadata and package contents before upload:

```bash
python - <<'PY'
from pathlib import Path
import tarfile, zipfile
for artifact in sorted(Path('dist').iterdir()):
    print(f"\n== {artifact.name} ==")
    if artifact.suffix == '.whl':
        with zipfile.ZipFile(artifact) as zf:
            print('\n'.join(sorted(zf.namelist())[:80]))
    elif artifact.name.endswith('.tar.gz'):
        with tarfile.open(artifact, 'r:gz') as tf:
            print('\n'.join(sorted(m.name for m in tf.getmembers())[:80]))
PY
```

## Optional TestPyPI rehearsal

Use TestPyPI only after local verification passes. This step requires maintainer credentials and is intentionally not automated by repository scripts.

```bash
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
python -m venv /tmp/nudge-testpypi-venv
/tmp/nudge-testpypi-venv/bin/python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ nudge-ai-life-coach
/tmp/nudge-testpypi-venv/bin/nudge --help
rm -rf /tmp/nudge-testpypi-venv
```

If TestPyPI dependency resolution is noisy, use the same clean virtual environment pattern and install the exact artifact file from `dist/` for smoke testing.

## Production PyPI release

Only run this after the local checks and any TestPyPI rehearsal are accepted:

```bash
python -m twine check dist/*
python -m twine upload dist/*
```

After upload, verify public installation from a clean environment:

```bash
pipx install nudge-ai-life-coach
nudge --help
nudge doctor --help
nudge docs audit --json
pipx uninstall nudge-ai-life-coach
```

Then update release notes, mark the version as published in `CHANGELOG.md`, and decide whether a Homebrew tap is worth preparing.

## Failure handling and rollback notes

PyPI releases are immutable in practice: you cannot replace an uploaded file for the same version, and deleting a file or project can break users and does not let you safely reuse the version. If a bad artifact is uploaded:

1. Stop further uploads for that version.
2. Document the issue in release notes.
3. Yank the release on PyPI if users should avoid it but dependency resolution may still need it.
4. Publish a fixed patch version instead of trying to overwrite the broken artifact.
5. Rotate any credential that might have been exposed during the release process.

Homebrew publication remains a separate future task. Do not update a formula until the PyPI artifact is verified or a source archive URL is intentionally chosen.
