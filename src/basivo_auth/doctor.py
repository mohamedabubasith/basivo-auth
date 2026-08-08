"""Environment preflight checks.

Run standalone via ``basivo-auth doctor`` and automatically before generation, so
a project is never scaffolded into an environment that cannot build it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from packaging.version import InvalidVersion, Version


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str
    remedy: str = ""

    @property
    def blocking(self) -> bool:
        return self.status is Status.FAIL


def _run(*args: str, timeout: int = 10) -> str | None:
    """Return trimmed stdout, or None if the command is missing or fails."""
    executable = shutil.which(args[0])
    if executable is None:
        return None
    try:
        proc = subprocess.run(
            [executable, *args[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr).strip()


def _extract_version(text: str) -> Version | None:
    for token in text.replace("(", " ").replace(")", " ").split():
        cleaned = token.lstrip("v")
        # Trim vendor suffixes such as Apple's "2.39.5" in "git version 2.39.5 (Apple...)".
        cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch == ".").strip(".")
        if not cleaned or "." not in cleaned:
            continue
        try:
            return Version(cleaned)
        except InvalidVersion:
            continue
    return None


def check_python() -> Check:
    current = Version(f"{sys.version_info.major}.{sys.version_info.minor}")
    if current < Version("3.11"):
        return Check(
            "python",
            Status.FAIL,
            f"running on {current}, need >= 3.11",
            "Install with `uv python install 3.12`, then reinstall basivo-auth.",
        )
    return Check("python", Status.OK, f"{sys.version.split()[0]}")


def check_git() -> Check:
    raw = _run("git", "--version")
    if raw is None:
        return Check(
            "git",
            Status.FAIL,
            "not found",
            "Install git — generated projects are git repos so `copier update` can work.",
        )
    version = _extract_version(raw)
    if version is not None and version < Version("2.30"):
        return Check(
            "git",
            Status.WARN,
            f"{version} is old",
            "Upgrade to >= 2.30; older versions have known `git apply` edge cases "
            "that break `copier update`.",
        )
    return Check("git", Status.OK, str(version or raw))


def check_uv() -> Check:
    raw = _run("uv", "--version")
    if raw is None:
        return Check(
            "uv",
            Status.WARN,
            "not found",
            "Install uv (https://docs.astral.sh/uv/) to auto-install generated "
            "project dependencies. Generation still works without it.",
        )
    return Check("uv", Status.OK, str(_extract_version(raw) or raw))


def check_docker() -> Check:
    raw = _run("docker", "--version")
    if raw is None:
        return Check(
            "docker",
            Status.WARN,
            "not found",
            "Needed only to run the generated docker-compose stack (Postgres + Redis) locally.",
        )
    return Check("docker", Status.OK, str(_extract_version(raw) or raw))


def check_xmlsec() -> Check:
    """SAML support needs xmlsec1 headers at pip-install time, not just runtime."""
    if shutil.which("xmlsec1") is not None:
        return Check("xmlsec", Status.OK, "xmlsec1 present (SAML available)")
    return Check(
        "xmlsec",
        Status.WARN,
        "xmlsec1 not found",
        "Only required for the SAML feature. macOS: `brew install libxmlsec1 pkg-config`. "
        "Debian/Ubuntu: `apt install libxmlsec1-dev pkg-config`.",
    )


def run_checks(*, include_saml: bool = False) -> list[Check]:
    checks = [check_python(), check_git(), check_uv(), check_docker()]
    if include_saml:
        checks.append(check_xmlsec())
    return checks


def blocking_failures(checks: list[Check]) -> Iterator[Check]:
    return (check for check in checks if check.blocking)
