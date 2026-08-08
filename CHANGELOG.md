# Changelog

Notable changes to `basivo-auth`.

This project generates code rather than shipping a library, so entries are
written for two audiences: people running the CLI, and people whose existing
projects will pull the change through `basivo-auth update`. Anything that
changes generated behaviour says so explicitly.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are git tags — `copier update` compares them to work out what changed,
so a released tag is never moved.

## [Unreleased]

### Added
- Contributor infrastructure: CI for the generator itself (lint, types, tests,
  plus generating and verifying real projects across presets, both state
  backends, three Terraform targets, and an embedded install), issue and PR
  templates, `SECURITY.md`, `CONTRIBUTING.md`, Dependabot.

## [0.1.0] — 2026-08-08

First release.

### Added

**Two install modes, one template**
- `basivo-auth new` generates a standalone, deployable auth service.
- `basivo-auth init` installs auth into an existing FastAPI project, adopting
  its SQLAlchemy `Base`, session dependency and migrations. Auth tables land on
  the host's metadata, so the host's `alembic revision --autogenerate` picks
  them up and its own tables can foreign-key to `user`.
- `basivo-auth update` pulls template fixes into a generated project while
  preserving local edits — the reason this is a generator with a thread back
  rather than a one-shot scaffolder.

**Authentication**
- Register, login, logout, email verification, forgot/reset/change password.
- Email and SMS one-time codes, TOTP two-factor with QR enrolment and
  single-use recovery codes, magic-link sign-in, social and OIDC SSO.
- Refresh-token rotation with **reuse detection**: replaying a rotated token
  revokes the entire token family and raises an audit event.

**Authorization**
- Per-organisation roles and permissions. Routes name permissions, never roles.
- Authority is re-read from the database per request, so a demotion applies
  immediately rather than at token expiry.
- Escalation guards: no granting above your own rank, no acting on someone who
  outranks you, no demoting the last owner, no changing your own role. Blocked
  attempts are audited as `authz_escalation_blocked`.
- Non-members receive 404 rather than 403, so organisation IDs are not
  enumerable.

**Hardening**
- Argon2id via `pwdlib` (`passlib` is unmaintained and does not import on
  Python 3.13+).
- Purpose-bound JWT audiences, so a pending-2FA step-up token cannot
  authenticate an API route.
- Identical response *and timing* on login and forgot-password.
- Progressive, capped account lockout; Redis-backed rate limits.
- HttpOnly cookies, double-submit CSRF, strict security headers.
- Settings that refuse to start on a placeholder secret, a wildcard CORS origin,
  or debug mode in production.
- Secrets generated locally at `0600` and gitignored before the first commit.

**Infrastructure**
- Selectable state backend: Redis, or your SQL database with no Redis to run.
  Lockout, OTP and single-use markers behave identically; rate limiting moves to
  the edge, which the generated Terraform configures.
- Terraform for AWS ECS/Fargate and Lambda, validated with `terraform validate`.
  Lambda uses `NullPool` with RDS Proxy and loads secrets at cold start.
- Docker Compose for local development, Alembic migrations, an operator CLI, and
  CI running ruff, mypy, bandit, pip-audit, gitleaks and semgrep.

### Notes

- Built on `fastapi-users` 15.x, which entered maintenance mode in March 2026.
  Every import of it is confined to the generated `engine/` package, enforced by
  a ruff rule and a CI job, so a future migration is one package rather than a
  rewrite.
- Passkeys and SAML generate settings and dependencies but no routes yet.
  Passkeys is off in every preset; SAML is enabled by the `enterprise` preset.

[Unreleased]: https://github.com/mohamedabubasith/basivo-auth/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mohamedabubasith/basivo-auth/releases/tag/v0.1.0
