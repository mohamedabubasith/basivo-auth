"""Answer model shared by the interactive prompts, the CLI flags and Copier.

This module is the single source of truth for what a generated project can be
configured with. ``copier.yml`` mirrors these names; :func:`ProjectAnswers.to_copier`
produces the exact dict Copier is handed, so the two can never silently diverge.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

# A project slug becomes a Python package name, a Docker service name and a
# directory name, so it has to satisfy the intersection of all three.
SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")

# Slugs that would shadow the generated package's own top-level imports.
RESERVED_SLUGS = frozenset({"app", "tests", "test", "alembic", "src", "auth", "basivo_auth"})


class Feature(StrEnum):
    """Optional capabilities that can be toggled per generated project.

    Core auth (register / login / logout / forgot / reset / verify) is never a
    feature: it is always generated. These are the things that cost extra
    dependencies, extra routes or extra operational burden.
    """

    OTP = "otp"
    """Email or SMS one-time codes: passwordless login and step-up auth."""

    TOTP = "totp"
    """Authenticator-app 2FA (RFC 6238) with QR provisioning and recovery codes."""

    MAGIC_LINK = "magic_link"
    """Single-use signed login links delivered by email."""

    SSO = "sso"
    """Social / enterprise OAuth2 + OpenID Connect login."""

    PASSKEYS = "passkeys"
    """WebAuthn / FIDO2 passkey registration and login."""

    SAML = "saml"
    """SAML 2.0 SSO. Requires system xmlsec; off by default."""

    ORGS = "orgs"
    """Multi-tenant organisations with per-organisation roles and permissions.

    Generates the authorization layer: Role/Permission enums, the
    ``require(Permission.X)`` dependency, escalation guards and the
    organisation/membership API. Without it a project has authentication but
    no access control beyond the ``is_superuser`` flag."""

    @property
    def label(self) -> str:
        return {
            Feature.OTP: "Email/SMS OTP (passwordless + step-up)",
            Feature.TOTP: "TOTP 2FA (authenticator apps)",
            Feature.MAGIC_LINK: "Magic-link login",
            Feature.SSO: "Social + OIDC SSO",
            Feature.PASSKEYS: "Passkeys (WebAuthn)",
            Feature.SAML: "SAML 2.0 SSO (needs system xmlsec)",
            Feature.ORGS: "Organisations + per-org roles/permissions (multi-tenant authz)",
        }[self]


class Preset(StrEnum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"

    @property
    def features(self) -> frozenset[Feature]:
        return {
            Preset.MINIMAL: frozenset(),
            Preset.STANDARD: frozenset({Feature.OTP, Feature.TOTP, Feature.SSO}),
            Preset.ENTERPRISE: frozenset(
                {
                    Feature.OTP,
                    Feature.TOTP,
                    Feature.MAGIC_LINK,
                    Feature.SSO,
                    Feature.SAML,
                    Feature.ORGS,
                }
            ),
        }[self]

    @property
    def description(self) -> str:
        return {
            Preset.MINIMAL: "Register, login, forgot/reset password, email verification.",
            Preset.STANDARD: "Minimal + OTP + TOTP 2FA + social SSO.",
            Preset.ENTERPRISE: "Standard + magic link + SAML + multi-tenant authorization.",
        }[self]


class DeployTarget(StrEnum):
    """Where the generated service is meant to run."""

    NONE = "none"
    """No cloud infrastructure generated. Docker Compose for local work only."""

    ECS = "ecs"
    """AWS ECS on Fargate, behind an ALB. Long-lived containers."""

    LAMBDA = "lambda"
    """AWS Lambda behind API Gateway. Serverless, with the trade-offs in docs."""

    BOTH = "both"
    """Terraform for both, selectable per environment."""

    @property
    def has_ecs(self) -> bool:
        return self in (DeployTarget.ECS, DeployTarget.BOTH)

    @property
    def has_lambda(self) -> bool:
        return self in (DeployTarget.LAMBDA, DeployTarget.BOTH)

    @property
    def has_terraform(self) -> bool:
        return self is not DeployTarget.NONE


class StateBackend(StrEnum):
    """Where short-lived security state lives: lockout counters, OTP codes,
    magic-link single-use markers and rate-limit counters."""

    REDIS = "redis"
    """Fast, expiring, shared across every worker. The right default."""

    DATABASE = "database"
    """Your existing SQL database, no Redis to run.

    Lockout, OTP and single-use markers work identically. Rate limiting does
    not move here — a counter write on every request is the wrong shape for a
    relational database — so it falls back to per-process limits, and the
    generated Terraform configures API Gateway throttling instead."""


class InstallMode(StrEnum):
    """How the generated auth code is delivered."""

    SERVICE = "service"
    """A standalone, deployable auth service with its own database and build."""

    EMBEDDED = "embedded"
    """A package inside an existing FastAPI project, sharing its database."""


class Database(StrEnum):
    POSTGRES = "postgres"
    SQLITE = "sqlite"

    @property
    def is_async_capable(self) -> bool:
        return True

    @property
    def driver(self) -> str:
        return {
            Database.POSTGRES: "postgresql+asyncpg",
            Database.SQLITE: "sqlite+aiosqlite",
        }[self]


class TokenTransport(StrEnum):
    """How the access token reaches the client.

    ``cookie`` is the right default for first-party browser apps: the token is
    unreadable from JavaScript, which removes the entire class of XSS token
    exfiltration. ``bearer`` suits native/mobile clients and service-to-service.
    ``both`` mounts two independent backends on separate route prefixes.
    """

    COOKIE = "cookie"
    BEARER = "bearer"
    BOTH = "both"

    @property
    def has_cookie(self) -> bool:
        return self in (TokenTransport.COOKIE, TokenTransport.BOTH)

    @property
    def has_bearer(self) -> bool:
        return self in (TokenTransport.BEARER, TokenTransport.BOTH)


class EmailProvider(StrEnum):
    SMTP = "smtp"
    RESEND = "resend"
    SES = "ses"
    WEBHOOK = "webhook"
    """POSTs the rendered email to a URL you control, which does the sending.

    For an automation platform — n8n, Make, Zapier — or an internal mail
    service. It lets the sending account be one this service never holds
    credentials for: an operator connects Gmail to n8n over OAuth, and this
    service only ever knows the webhook URL.

    Note what that implies. The payload carries password-reset and email
    verification links, which are credentials. Whatever is on the other end can
    read them, and so can anything that logs the request. The generated code
    requires HTTPS in production and signs every request for that reason.
    """

    CONSOLE = "console"
    """Writes the rendered email to stdout. Development only."""


class ProjectAnswers(BaseModel):
    """Everything Copier needs to render a project."""

    model_config = {"frozen": True, "extra": "forbid"}

    project_slug: str = Field(description="Directory and package name, e.g. 'acme-auth'.")
    project_name: str = Field(default="", description="Human-readable name.")
    project_description: str = Field(default="Authentication service.")

    preset: Preset = Preset.STANDARD
    features: frozenset[Feature] = Field(default_factory=frozenset)

    database: Database = Database.POSTGRES
    token_transport: TokenTransport = TokenTransport.COOKIE
    email_provider: EmailProvider = EmailProvider.SMTP

    python_version: str = "3.12"

    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    """15 minutes. Short enough that a leaked access token has a small blast radius."""

    refresh_token_ttl_seconds: int = Field(default=2_592_000, ge=3600)
    """30 days. Rotated on every use, so age alone is not the security boundary."""

    include_docker: bool = True
    include_ci: bool = True
    include_admin_cli: bool = True

    install_mode: InstallMode = InstallMode.SERVICE

    deploy_target: DeployTarget = DeployTarget.NONE
    state_backend: StateBackend = StateBackend.REDIS

    host_db_module: str = "app.db"
    """Embedded only: module holding the host's Base and session dependency."""

    host_base_name: str = "Base"
    host_session_dependency: str = "get_async_session"

    tests_dir: str = "tests"

    package_dir: str = "app"
    """Directory (and import name) of the generated Python package.

    ``app`` for a standalone service. In embedded mode the CLI overrides this
    with a package name inside the host project, which is what lets one template
    serve both without a second copy of every file."""

    @field_validator("project_slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not SLUG_RE.match(value):
            raise ValueError(
                f"{value!r} is not a valid slug: use lowercase letters, digits, "
                "'-' or '_', starting with a letter (e.g. 'acme-auth')."
            )
        if value.replace("-", "_") in RESERVED_SLUGS:
            raise ValueError(f"{value!r} is reserved and would shadow a generated module.")
        return value

    @field_validator("package_dir")
    @classmethod
    def _validate_package_dir(cls, value: str) -> str:
        value = value.strip().strip("/")
        segments = value.split("/")
        if not segments or not all(
            segment.isidentifier() and segment.islower() for segment in segments
        ):
            raise ValueError(
                f"{value!r} must be lowercase path segments that are valid Python "
                "identifiers, e.g. 'app' or 'myapp/auth'."
            )
        return value

    @field_validator("python_version")
    @classmethod
    def _validate_python(cls, value: str) -> str:
        if value not in {"3.11", "3.12", "3.13"}:
            raise ValueError(f"Unsupported Python {value}; choose 3.11, 3.12 or 3.13.")
        return value

    @model_validator(mode="after")
    def _apply_preset_and_deps(self) -> Self:
        features = set(self.features) | set(self.preset.features)

        # SAML and passkeys are SSO-adjacent but independent; orgs imply nothing.
        # TOTP recovery codes and OTP share the delivery + hashing primitives, but
        # each generates its own module, so no implication is forced here.
        object.__setattr__(self, "features", frozenset(features))

        if not self.project_name:
            pretty = self.project_slug.replace("-", " ").replace("_", " ").title()
            object.__setattr__(self, "project_name", pretty)
        return self

    @property
    def uses_redis(self) -> bool:
        return self.state_backend is StateBackend.REDIS

    @property
    def is_embedded(self) -> bool:
        return self.install_mode is InstallMode.EMBEDDED

    @property
    def package_module(self) -> str:
        """Dotted import path of the generated package."""
        return self.package_dir.replace("/", ".")

    @property
    def package_name(self) -> str:
        """Importable package directory inside the generated project."""
        return self.project_slug.replace("-", "_")

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def to_copier(self) -> dict[str, Any]:
        """Flatten to the exact answer dict Copier consumes.

        Booleans are emitted per-feature (``feature_otp`` …) rather than as a list
        because Jinja conditionals over booleans are far easier to read in
        templates than membership tests, and Copier's conditional file names need
        scalar expressions.

        Values that ``copier.yml`` derives itself (``package_name``,
        ``database_driver``, ``transport_cookie``, ``transport_bearer``) are
        deliberately **not** sent. They are declared there with ``when: false``,
        so Copier recomputes them on every update and they cannot drift.
        """
        answers: dict[str, Any] = {
            "project_slug": self.project_slug,
            "project_name": self.project_name,
            "project_description": self.project_description,
            "preset": self.preset.value,
            "database": self.database.value,
            "token_transport": self.token_transport.value,
            "email_provider": self.email_provider.value,
            "python_version": self.python_version,
            "access_token_ttl_seconds": self.access_token_ttl_seconds,
            "refresh_token_ttl_seconds": self.refresh_token_ttl_seconds,
            "include_docker": self.include_docker,
            "include_ci": self.include_ci,
            "include_admin_cli": self.include_admin_cli,
            "package_dir": self.package_dir,
            "tests_dir": self.tests_dir,
            "install_mode": self.install_mode.value,
            "deploy_target": self.deploy_target.value,
            "state_backend": self.state_backend.value,
            "host_db_module": self.host_db_module,
            "host_base_name": self.host_base_name,
            "host_session_dependency": self.host_session_dependency,
        }
        for feature in Feature:
            answers[f"feature_{feature.value}"] = feature in self.features
        return answers
