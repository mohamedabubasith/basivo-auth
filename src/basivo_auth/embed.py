"""Post-generation steps specific to embedding auth in an existing project.

Everything here is **additive and idempotent**. The host project's files belong
to the host: dependencies are appended, never rewritten; environment keys are
appended only if absent; nothing is reformatted. Running ``init`` twice must not
produce a different result from running it once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from basivo_auth.config import Database, EmailProvider, Feature, ProjectAnswers
from basivo_auth.detect import read_dependencies, requirement_name
from basivo_auth.postgen import build_env

#: Runtime dependencies the generated auth package needs. Kept in sync with the
#: service-mode pyproject template; anything the host already pins is skipped.
CORE_REQUIREMENTS: tuple[str, ...] = (
    "fastapi>=0.115.0",
    "fastapi-users[sqlalchemy]>=15.0.5,<16",
    "pwdlib[argon2]>=0.2.1",
    "pyjwt>=2.10.0",
    "cryptography>=44.0.0",
    "sqlalchemy[asyncio]>=2.0.36",
    "redis>=5.2.0",
    "pydantic[email]>=2.10.0",
    "pydantic-settings>=2.6.0",
    "httpx>=0.28.0",
    "slowapi>=0.1.9",
    "structlog>=24.4.0",
    "jinja2>=3.1.4",
    "python-multipart>=0.0.18",
)

FEATURE_REQUIREMENTS: dict[Feature, tuple[str, ...]] = {
    Feature.OTP: ("pyotp>=2.9.0",),
    Feature.TOTP: ("pyotp>=2.9.0", "qrcode[pil]>=8.0"),
    Feature.SSO: ("httpx-oauth>=0.16.0", "authlib>=1.3.2"),
    Feature.PASSKEYS: ("webauthn>=2.3.0",),
    Feature.SAML: ("python3-saml>=1.16.0",),
}

EMAIL_REQUIREMENTS: dict[EmailProvider, tuple[str, ...]] = {
    EmailProvider.SMTP: ("aiosmtplib>=3.0.2",),
    EmailProvider.SES: ("aioboto3>=13.2.0",),
}

#: Needed only to run the generated test suite. Kept out of the runtime merge so
#: `init` never adds test tooling to a project's production dependencies.
TEST_REQUIREMENTS: tuple[str, ...] = (
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "anyio>=4.6.0",
    "aiosqlite>=0.20.0",
    "fakeredis>=2.26.1",
    "asgi-lifespan>=2.1.0",
)

DATABASE_REQUIREMENTS: dict[Database, tuple[str, ...]] = {
    Database.POSTGRES: ("asyncpg>=0.30.0",),
    Database.SQLITE: ("aiosqlite>=0.20.0",),
}


@dataclass(slots=True)
class EmbedReport:
    added_requirements: list[str] = field(default_factory=list)
    skipped_requirements: list[str] = field(default_factory=list)
    env_keys_added: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_steps: list[str] = field(default_factory=list)


def required_packages(answers: ProjectAnswers) -> list[str]:
    """Every runtime requirement the generated code imports."""
    requirements: list[str] = list(CORE_REQUIREMENTS)
    requirements += DATABASE_REQUIREMENTS.get(answers.database, ())
    requirements += EMAIL_REQUIREMENTS.get(answers.email_provider, ())
    for feature in sorted(answers.features, key=lambda item: item.value):
        requirements += FEATURE_REQUIREMENTS.get(feature, ())

    seen: dict[str, str] = {}
    for requirement in requirements:
        seen.setdefault(requirement_name(requirement), requirement)
    return list(seen.values())


def merge_dependencies(
    project_root: Path,
    answers: ProjectAnswers,
    report: EmbedReport,
) -> None:
    """Append missing requirements to the host's ``[project.dependencies]``.

    Edited as text rather than parsed-and-rewritten: ``tomllib`` is read-only,
    and a full round-trip through a writer would reorder keys and strip the
    comments in a file we do not own.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.is_file():
        report.warnings.append("No pyproject.toml found; add these yourself:")
        report.warnings.extend(f"    {item}" for item in required_packages(answers))
        return

    existing = {requirement_name(item) for item in read_dependencies(pyproject)}
    missing = [
        item for item in required_packages(answers) if requirement_name(item) not in existing
    ]
    report.skipped_requirements = [
        item for item in required_packages(answers) if requirement_name(item) in existing
    ]

    if not missing:
        return

    text = pyproject.read_text(encoding="utf-8")
    opening = re.search(r"^dependencies\s*=\s*\[", text, re.MULTILINE)
    if opening is None:
        report.warnings.append("Could not find a [project] dependencies array; add these yourself:")
        report.warnings.extend(f"    {item}" for item in missing)
        return

    # Append at the end of the array, not the start. Inserting at the top would
    # put the "added by basivo-auth" marker above the project's own entries,
    # making it read as though the tool had added all of them.
    closing = _find_array_close(text, opening.end() - 1)
    if closing is None:
        report.warnings.append("Could not parse the dependencies array; add these yourself:")
        report.warnings.extend(f"    {item}" for item in missing)
        return

    block = (
        "\n    # --- added by basivo-auth ---\n"
        + "\n".join(f'    "{item}",' for item in missing)
        + "\n"
    )

    head = text[:closing].rstrip()
    if head.endswith("["):
        prefix = head + "\n"
    else:
        prefix = head + ("" if head.endswith(",") else ",") + "\n"

    pyproject.write_text(prefix + block.lstrip("\n") + text[closing:], encoding="utf-8")
    report.added_requirements = missing


def _find_array_close(text: str, open_bracket: int) -> int | None:
    """Index of the ``]`` closing the array that opens at ``open_bracket``."""
    depth = 0
    for index in range(open_bracket, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def merge_env(project_root: Path, answers: ProjectAnswers, report: EmbedReport) -> None:
    """Append auth settings to the host's .env, generating fresh secrets.

    Existing keys are never touched — the host may already define
    ``DATABASE_URL`` or ``REDIS_URL``, and auth deliberately reuses those rather
    than introducing a second source of truth.
    """
    env_values = build_env(answers)

    # Owned by the host in embedded mode: auth shares the same database and
    # connection, so overriding these would point auth at a different store.
    for key in ("DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        env_values.pop(key, None)

    for filename, keep_values in ((".env", True), (".env.example", False)):
        path = project_root / filename
        existing_text = path.read_text(encoding="utf-8") if path.is_file() else ""
        present = {
            line.split("=", 1)[0].strip()
            for line in existing_text.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }

        missing = {key: value for key, value in env_values.items() if key not in present}
        if not missing:
            continue

        lines = ["", "# --- basivo-auth ---"]
        if keep_values:
            lines.append("# Secrets generated locally. Never commit this file.")
        lines += [
            f"{key}={value if keep_values or _is_safe_placeholder(key) else ''}"
            for key, value in missing.items()
        ]

        with path.open("a", encoding="utf-8") as handle:
            if existing_text and not existing_text.endswith("\n"):
                handle.write("\n")
            handle.write("\n".join(lines) + "\n")

        if filename == ".env":
            report.env_keys_added = sorted(missing)
            path.chmod(0o600)


def _is_safe_placeholder(key: str) -> bool:
    return not any(marker in key for marker in ("SECRET", "PASSWORD", "TOKEN", "KEY", "API"))


def ensure_gitignored(project_root: Path, report: EmbedReport) -> None:
    gitignore = project_root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    patterns = {line.strip() for line in existing.splitlines()}
    missing = [item for item in (".env", ".env.*", "!.env.example") if item not in patterns]
    if not missing:
        return

    with gitignore.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(
            "\n# --- basivo-auth: never commit local secrets ---\n" + "\n".join(missing) + "\n"
        )


def wiring_snippet(answers: ProjectAnswers, app_module: str, app_variable: str) -> str:
    """The lines the developer adds to their FastAPI app."""
    module = answers.package_module
    return (
        f"from {module}.router import auth_router, install_auth\n"
        "\n"
        f"install_auth({app_variable})          # security headers"
        f"{', CSRF' if answers.token_transport.has_cookie else ''}, rate limits\n"
        f"{app_variable}.include_router(auth_router)\n"
    )


def alembic_snippet(answers: ProjectAnswers) -> str:
    """The import that makes the host's autogenerate see the auth tables."""
    return (
        f"# Registers the auth tables on your Base.metadata so autogenerate\n"
        f"# emits them. Import for the side effect only.\n"
        f"from {answers.package_module} import models  # noqa: F401\n"
    )


def build_manual_steps(
    answers: ProjectAnswers,
    app_module: str,
    app_variable: str,
    has_alembic: bool,
) -> list[str]:
    steps = [
        "Install the new dependencies:  uv sync   (or pip install -e .)",
        f"Wire the router into {app_module or 'your FastAPI app'}:\n"
        + "\n".join(
            f"      {line}"
            for line in wiring_snippet(answers, app_module, app_variable).splitlines()
        ),
    ]
    if has_alembic:
        steps.append(
            "Add this to alembic/env.py, then autogenerate a migration:\n"
            + "\n".join(f"      {line}" for line in alembic_snippet(answers).splitlines())
            + '\n      alembic revision --autogenerate -m "add auth tables"'
            + "\n      alembic upgrade head"
        )
    else:
        steps.append(
            "Set up Alembic and create the auth tables — auth adds "
            f"{'8' if answers.has(Feature.ORGS) else '4'} tables to your database."
        )
    steps.append("Fill in the blank values in .env (SMTP/OAuth credentials).")
    steps.append(
        "To run the generated tests (tests/auth/), add these dev dependencies\n"
        "      and register the marker in your pytest config:\n"
        + "\n".join(f"      {item}" for item in TEST_REQUIREMENTS)
        + '\n      asyncio_mode = "auto"'
        + '\n      markers = ["security: encodes a specific security control"]'
    )
    return steps
