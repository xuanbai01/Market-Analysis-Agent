"""
The production image (Dockerfile) pip-installs its own pinned package
list instead of reading pyproject.toml, so the two drift silently:
adding a dependency to pyproject and uv.lock passes every test and CI
job, then the Fly deploy boots an image without it.

That happened twice. ``lxml`` and ``beautifulsoup4`` were pinned in
pyproject but never added to the Dockerfile (bs4 only arrived via
yfinance; without lxml, yfinance's earnings scraping returns empty
frames). ``openai`` (ADR 0006) would have crashed the app on import.
This test makes the drift a CI failure instead of a production outage.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# "name==1.2.3" or "name[extra]==1.2.3"; names compared case-insensitively.
_PIN_RE = re.compile(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==(\S+)$")


def _pyproject_pins() -> dict[str, str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["dependencies"]
    pins: dict[str, str] = {}
    for dep in deps:
        match = _PIN_RE.match(dep)
        assert match, f"runtime dependency {dep!r} must be pinned with =="
        pins[match.group(1).lower()] = match.group(2)
    return pins


def _dockerfile_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        token = line.strip().removesuffix("\\").strip()
        match = _PIN_RE.match(token)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def test_dockerfile_installs_every_runtime_dependency_at_its_pyproject_pin() -> None:
    assert _dockerfile_pins() == _pyproject_pins()
