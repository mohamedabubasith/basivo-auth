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

## [0.2.1] — 2026-08-09

### Fixed

**`--local` rendered the last release, not your working copy.** Copier resolves
a git source to a committed ref, so a contributor who edited the template and
ran `basivo-auth new --local` generated the previous version and never saw
their own change — while `CONTRIBUTING.md` promised the opposite. `--local` now
passes `vcs_ref=HEAD`, which includes uncommitted edits. This one silently
wasted debugging time on output that had nothing to do with the code in front
of you.

**The 2FA step-up token was not consumed on use.** Within its 300-second life
it could be exchanged at `/auth/2fa/verify` more than once, each exchange
minting another session. An attacker still needed a valid TOTP or recovery
code, so the exposure was bounded — but a credential that survives its own use
is one a proxy log, a crash report or a shared terminal can pass on inside the
window. The `jti` is now burned before the code is even checked, set-if-absent
so concurrent exchanges resolve to one winner. Announced as a known issue in
0.2.0.

**`install_auth` could not exempt an application's own API from CSRF.** A host
embedding this package alongside routes authenticated by an API key, an HMAC
signature or a client certificate had no way to say so, and the CSRF middleware
rejected those callers with "CSRF token missing" — wrong, and impossible to act
on. `install_auth(app, csrf_exempt_prefixes=("/flows",))` now exists; service
mode has a `CSRF_EXEMPT_PREFIXES` constant. Only exempt prefixes where no route
can be authorised by an ambient cookie.

**`init` under-reported what an embedded host needs.** It listed the test
dependencies but not `types-redis` / `types-qrcode`, nor the mypy override for
the engine modules — so an embedded install that ran mypy failed with errors
the standalone template already configures around. CI missed it because the
embed job runs pytest and never mypy.

**A generated docstring overflowed the line limit** when the package module
path was long, which happens in embedded mode. The project failed its own lint
depending on how it was named.

**Rich markup ate literal brackets in `init` output**, rendering
`[[tool.mypy.overrides]]` as an empty string — an instruction to add nothing.

## [0.2.0] — 2026-08-08

### Changed — **breaking, action required**

**Four secrets became one.** A generated project now configures a single
`SECRET_KEY`. `JWT_SECRET`, `REFRESH_TOKEN_SECRET` and `CSRF_SECRET` are gone.

Two of those three were never read. `REFRESH_TOKEN_SECRET` and `CSRF_SECRET`
were required at startup, validated for length, checked for distinctness — and
used by nothing. CSRF signing already derived its key from `SECRET_KEY`. They
were pure operational burden, and burden of exactly the kind that goes wrong:
four variables to provision per environment, any one of which could be missed,
weak, or accidentally copied between staging and production.

Every key is now derived from `SECRET_KEY` with HKDF-SHA256 under a distinct
label — `jwt`, `csrf`, `reset-password`, `verify-email`, `oauth-state` and
(with TOTP) `totp`. This keeps the property the separate variables were there
for: HKDF outputs are independent, so a leaked subkey reveals nothing about the
master or its siblings. What changes is who carries it. Derivation also closes
a gap the old scheme had — password reset and email verification tokens
previously used the raw `SECRET_KEY` directly, sharing a key with TOTP seed
encryption.

To upgrade an existing project:

```bash
basivo-auth update
# then delete JWT_SECRET, REFRESH_TOKEN_SECRET and CSRF_SECRET from .env
# and from your secret manager. SECRET_KEY stays as it is.
```

Because the JWT key is now derived rather than read from `JWT_SECRET`, tokens
signed before the upgrade will not verify after it. **Every session ends and
outstanding reset/verification links stop working**, once, at the deploy. Users
sign in again. Nothing is lost. Enrolled TOTP seeds are unaffected — they were
already encrypted under a key derived from `SECRET_KEY`, which does not change.

Generated Terraform drops the three `random_password` resources and writes one
key into Secrets Manager.

### Added
- `Settings.subkey(purpose)` / `subkey_str(purpose)` — the derivation used
  everywhere, with tests asserting subkeys are distinct per purpose,
  deterministic across processes, and all change when the master does.
- Contributor infrastructure: CI for the generator itself (lint, types, tests,
  plus generating and verifying real projects across presets, both state
  backends, three Terraform targets, and an embedded install), issue and PR
  templates, `SECURITY.md`, `CONTRIBUTING.md`, Dependabot.

### Known issues
- The 2FA step-up token is not consumed on use. Within its 300-second lifetime
  it can be exchanged at `/auth/2fa/verify` more than once, each time minting a
  session — an attacker still needs a valid TOTP or recovery code to do so.
  **Fixed in 0.2.1.**

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

[Unreleased]: https://github.com/mohamedabubasith/basivo-auth/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/mohamedabubasith/basivo-auth/releases/tag/v0.2.1
[0.2.0]: https://github.com/mohamedabubasith/basivo-auth/releases/tag/v0.2.0
[0.1.0]: https://github.com/mohamedabubasith/basivo-auth/releases/tag/v0.1.0
