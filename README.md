# basivo-auth

Scaffold production-hardened FastAPI authentication services — and keep every
generated project patchable from one template.

```bash
uv tool install "git+https://github.com/mohamedabubasith/basivo-auth@v0.1.0"
basivo-auth new acme-auth
```

Not published to PyPI or npm by design. Versions are git tags.

## Why it exists

Auth is the same problem every time, it is security-critical, and the hosted
options are metered per user. This generates a service you own, from free
components, with the controls that usually get skipped already wired in.

The part that matters more than the scaffold: **generated projects can pull
template updates**. Fix a vulnerability here, tag a release, then run
`basivo-auth update` in each product. A plain scaffolder leaves every project to
drift and be patched by hand.

## Two ways to use it

**A standalone auth service** — one deployment, many products call it:

```bash
basivo-auth new acme-auth
```

**Installed into an existing FastAPI project** — auth lives in your codebase and
shares your database:

```bash
cd my-existing-api
basivo-auth init --dry-run     # see exactly what would change
basivo-auth init
```

`init` generates `<your-package>/auth/` that imports **your** declarative Base
and **your** session dependency. Auth tables land on your metadata, so your
existing `alembic revision --autogenerate` picks them up, auth shares your
connection pool, and your own tables can foreign-key to `user`.

Nothing is overwritten: dependencies are appended to your `pyproject.toml`,
settings are appended to your `.env` with freshly generated secrets, and the
three lines to wire into your app are printed for you to paste.

```python
from myapp.auth.router import auth_router, install_auth

install_auth(app)  # security headers, CSRF, rate limits
app.include_router(auth_router)
```

## Commands

```
basivo-auth new <slug>       Generate a standalone auth service
basivo-auth init             Install auth into an existing FastAPI project
basivo-auth update           Pull template fixes into this project
basivo-auth add <feature>    Enable a feature in an existing project
basivo-auth doctor           Check the local toolchain
basivo-auth secrets rotate   Regenerate secrets in a project's .env
```

### Presets

| Preset | Contents |
| --- | --- |
| `minimal` | Register, login, forgot/reset, email verification |
| `standard` *(default)* | Minimal + OTP + TOTP 2FA + social SSO |
| `enterprise` | Standard + magic link + SAML + multi-tenant authorization |

Features are independently toggleable: `--features otp,totp,sso,magic_link,passkeys,saml,orgs`.

### Which mode?

| | `new` (service) | `init` (embedded) |
| --- | --- | --- |
| Output | Its own deployable project | `<pkg>/auth/` in your project |
| Database | Own engine, own migrations | **Your** Base, session and migrations |
| Best for | Several products sharing one sign-on | A single app |
| Integration | HTTP + JWT verification | `app.include_router(auth_router)` |
| Foreign keys to `user` | Not possible | Yes |
| `basivo-auth update` | Whole project | Only `<pkg>/auth/` and `tests/auth/` |

Both modes generate the same auth code from the same template, so a fix made
once reaches both.

## What gets generated

FastAPI + SQLAlchemy 2 (async) + Postgres + Redis, with a test suite whose
assertions *are* the security controls. Service mode adds Alembic, a
docker-compose stack, an operator CLI, a Dockerfile, and CI running ruff, mypy,
bandit, pip-audit, gitleaks and semgrep; embedded mode leaves all of that to the
project you are installing into.

Everything is environment-driven — 70+ settings, nothing hardcoded — so pointing
at your own Postgres, Redis or email provider is a matter of `DATABASE_URL`,
`REDIS_URL` and `EMAIL_PROVIDER`. The generated `docker-compose.yml` is a
local-development convenience, not a dependency.

Security posture — the full rationale lands in each project's `docs/security.md`:

- Argon2id via `pwdlib` (`passlib` is unmaintained and breaks on Python 3.13+)
- Refresh token rotation with **reuse detection**: a replayed token revokes the
  whole family
- Purpose-bound JWT audiences, so a pending-2FA token cannot act as an access token
- Uniform response *and timing* on login and forgot-password — no account enumeration
- Progressive, capped lockout; Redis-backed rate limits that hold across workers
- HttpOnly cookies, double-submit CSRF, strict security headers
- Settings that refuse to boot on a placeholder secret, wildcard CORS, or debug
  in production
- Secrets generated locally at `0600` and gitignored before the first commit

Everything used is MIT/BSD and self-hosted. No paid tier, no seat limits.

## The engine seam

Generated projects build on [`fastapi-users`](https://github.com/fastapi-users/fastapi-users)
(v15.x, MIT), which entered maintenance mode in March 2026 — still
security-patched, no new features, successor in development.

It is still the right base: battle-tested, externally reviewed, and the
alternative is owning thousands of lines of security-critical flow logic. The
risk is a future migration, so every `fastapi_users` import is confined to
`app/auth/engine/`, enforced by a ruff rule *and* a CI job. Swapping engines
later is a change to one package; routers, models and tests do not move.

## Updating generated projects

```bash
cd acme-auth
basivo-auth update      # copier update under the hood
git diff                # review, then commit
```

Requires the project to be a clean git repo with its `.copier-answers.yml`
intact — `basivo-auth new` sets both up. If the template has drifted too far,
`copier recopy` regenerates while keeping your answers.

Projects generated with `--local` cannot update: the bundled template has no git
history to diff against.

## Pointing at your own fork

The compiled-in template URL can be overridden without editing code:

```bash
export BASIVO_AUTH_TEMPLATE="git+https://github.com/your-org/basivo-auth.git"
```

## Requirements

Python 3.11+, git 2.30+. `uv` and Docker are optional but assumed by the
generated quick-start. Run `basivo-auth doctor` to check.

## Development

```bash
uv sync
uv tool install --editable .
basivo-auth new demo --local --defaults --no-install
uv run pytest
```

## Contributing

Bug reports, features and pull requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). It documents the rules that are enforced
(the engine seam, conditional filenames, why you must never hand-tune Jinja
whitespace) and how to test what you changed, since `pytest` alone checks the
generator rather than what it produces.

Found a security issue? **Do not open an issue** — see [SECURITY.md](SECURITY.md).

## License

MIT.
