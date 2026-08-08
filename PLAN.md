# basivo-auth — Build Plan

A Python CLI that scaffolds a production-hardened FastAPI authentication service.
Installed from a GitHub URL. Never published to PyPI or npm.

```bash
uv tool install "git+https://github.com/<org>/basivo-auth@v0.1.0"
basivo-auth new my-product-auth
```

---

## 1. Core decisions

| Decision | Choice | Why |
|---|---|---|
| Generated stack | FastAPI + SQLAlchemy 2 (async) + PostgreSQL + Redis | Matches your stack; async throughout |
| Auth engine | `fastapi-users` 15.x behind an adapter seam | See §2 — covers ~60% of features for free |
| CLI framework | Typer + Rich | Standard, typed, good help output |
| Templating | **Copier** (not Cookiecutter) | See §3 — supports `copier update` |
| Distribution | `uv tool install git+https://...@vX.Y.Z` | No registry, git tags = versions |
| Protection model | Hardened generated code (§6) | Not obfuscation — real security controls |

### Naming
- CLI package: `basivo_auth`
- Console script: `basivo-auth`
- Generated service default: `<name>-auth`

---

## 2. The `fastapi-users` situation — and the seam

**Finding:** `fastapi-users` v15.0.5 is officially in maintenance mode as of March 2026.
Security + dependency updates continue; no new features. A successor toolkit is in
development but unnamed and unreleased.

**Decision: use it anyway, but wrap it.**

Rationale: maintenance mode ≠ abandoned. It is MIT, widely deployed, and still receives
security patches. Writing register/login/reset/verify/OAuth flows from scratch means owning
thousands of lines of security-critical code with no external review. That is a worse risk
than a stable dependency.

**The seam.** All `fastapi-users` imports live in exactly one package in the generated
project:

```
app/auth/engine/          # ← the ONLY place fastapi_users is imported
    __init__.py           # exports: get_user_manager, current_user, auth_backend, ...
    manager.py            # UserManager subclass — lifecycle hooks
    backends.py           # transports + strategies
    adapters.py           # DB adapter wiring
```

Everything else in the generated app imports from `app.auth.engine`, never from
`fastapi_users` directly. A CI lint rule enforces this:

```
ruff: flake8-tidy-imports banned-api → "fastapi_users" banned outside app/auth/engine/
```

When the successor ships, you rewrite `app/auth/engine/` (~400 lines) and every generated
product updates via `copier update`. Routers, models, tests, and business logic are untouched.

### What fastapi-users gives you free
- Register, login, logout
- Forgot password / reset password (token flow)
- Email verification
- Social OAuth2 login flow
- Transports: Authorization header (Bearer), Cookie
- Strategies: JWT, Database, Redis
- DB adapters: SQLAlchemy async, Beanie (MongoDB)
- Pluggable password validation
- Full OpenAPI schema

### What it does NOT give you — you build these
- Email/SMS OTP (passwordless + step-up)
- TOTP 2FA (authenticator apps)
- Magic link login
- Passkeys / WebAuthn
- SAML SSO
- Rate limiting, account lockout, audit log
- Refresh-token rotation with reuse detection
- Multi-tenant orgs / roles

---

## 3. Why Copier, not Cookiecutter

You said "my upcoming products" — plural. That is the deciding constraint.

Cookiecutter is fire-and-forget: generate once, and every product drifts independently.
When you find an auth bug six months later, you patch it by hand in every product.

Copier supports `copier update`: it diffs the template's old tag against the new tag and
applies that diff to an already-generated project, preserving your local edits and prompting
on conflicts.

```bash
# In any generated product, months later:
cd my-product-auth
copier update          # pulls latest security fixes from the template
```

Requirements for this to work (the CLI enforces all three at generation time):
1. Generated project keeps its `.copier-answers.yml`
2. Template repo is versioned with **git tags** (PEP 440 comparable)
3. Generated project is a **git repo** with a clean working tree

If an update ever breaks, `copier recopy` regenerates from scratch while keeping answers.

**This is the single highest-value design choice in the plan.** It turns the CLI from a
one-time scaffolder into a security patch distribution channel.

---

## 4. Library stack — all free, all OSS

### Core (always generated)
| Library | License | Role |
|---|---|---|
| `fastapi` | MIT | Framework |
| `fastapi-users[sqlalchemy,oauth]` 15.x | MIT | Register/login/reset/verify/OAuth2 |
| `pwdlib[argon2]` | MIT | Argon2id hashing — fastapi-users' default since v13; replaces the unmaintained `passlib`, which breaks on Python 3.13+ |
| `sqlalchemy[asyncio]` 2.x + `asyncpg` | MIT | Async ORM |
| `alembic` | MIT | Migrations |
| `redis` (redis-py) | MIT | OTP store, rate-limit counters, token denylist |
| `pydantic-settings` | MIT | Typed config from env |
| `pyjwt` | MIT | JWT (avoid `python-jose` — unmaintained) |
| `structlog` | MIT/Apache-2 | Structured audit logging |

### Feature plugins (conditional in template)
| Feature | Library | License | Notes |
|---|---|---|---|
| OTP (email/SMS) | `pyotp` 2.10 | MIT | HOTP/TOTP primitives; Redis for delivery state |
| TOTP 2FA | `pyotp` + `qrcode[pil]` | MIT | Authenticator apps, provisioning URI + QR |
| Social SSO | `httpx-oauth` | MIT | Google, GitHub, Microsoft, Okta, generic OIDC |
| Enterprise OIDC | `authlib` | BSD-3 | Discovery-document based OIDC for arbitrary IdPs |
| Magic link | *(no dep)* | — | Signed token + Redis single-use, ~60 lines |
| Passkeys | `webauthn` (py_webauthn) | BSD-3 | Optional; adds FIDO2 |
| SAML SSO | `python3-saml` | MIT | Optional; **requires system `xmlsec`/`libxml2`** — gate behind a flag, it complicates Docker builds |
| Rate limiting | `slowapi` | MIT | Redis-backed; wraps `limits` |
| Email delivery | `fastapi-mail` or `aiosmtplib` + Jinja2 | MIT | Pluggable: SMTP / Resend / SES |
| Breached-password check | HIBP Pwned Passwords **range API** | free, no key | k-anonymity — send 5 SHA-1 chars, never the password |

### CLI dependencies (your tool, not generated)
`typer`, `rich`, `copier`, `questionary` (optional richer prompts), `packaging`.

### Dev/CI (generated into the project)
`pytest`, `pytest-asyncio`, `httpx`, `testcontainers[postgres,redis]`,
`ruff`, `mypy --strict`, `bandit`, `pip-audit`, `gitleaks`, `semgrep`.

---

## 5. Repository layout

```
basivo-auth/
├── pyproject.toml                    # hatchling; [project.scripts] basivo-auth = ...
├── src/basivo_auth/
│   ├── __init__.py
│   ├── cli.py                        # Typer app: new / update / add / doctor / secrets
│   ├── prompts.py                    # interactive feature picker
│   ├── config.py                     # answer model (pydantic) — single source of truth
│   ├── runner.py                     # wraps copier.run_copy / run_update
│   ├── postgen.py                    # git init, secret gen, uv sync, alembic revision
│   └── doctor.py                     # env checks: python, uv, docker, git, xmlsec
├── template/                         # ← the Copier template
│   ├── copier.yml                    # questions, conditional file exclusion, _tasks
│   └── {{project_slug}}/
│       ├── pyproject.toml.jinja
│       ├── docker-compose.yml.jinja
│       ├── Dockerfile
│       ├── .env.example.jinja
│       ├── alembic/
│       ├── app/
│       │   ├── main.py.jinja
│       │   ├── settings.py.jinja
│       │   ├── db.py
│       │   ├── auth/
│       │   │   ├── engine/           # ← fastapi-users isolation seam (§2)
│       │   │   ├── routers/
│       │   │   │   ├── core.py       # register, login, logout, me
│       │   │   │   ├── password.py   # forgot, reset, change
│       │   │   │   ├── otp.py.jinja          {% if features.otp %}
│       │   │   │   ├── totp.py.jinja         {% if features.totp %}
│       │   │   │   ├── magic_link.py.jinja   {% if features.magic_link %}
│       │   │   │   ├── sso.py.jinja          {% if features.sso %}
│       │   │   │   ├── saml.py.jinja         {% if features.saml %}
│       │   │   │   └── passkeys.py.jinja     {% if features.passkeys %}
│       │   │   ├── security/         # ← the hardening layer (§6)
│       │   │   │   ├── ratelimit.py
│       │   │   │   ├── lockout.py
│       │   │   │   ├── tokens.py     # refresh rotation + reuse detection
│       │   │   │   ├── audit.py
│       │   │   │   ├── password_policy.py   # zxcvbn-ish + HIBP
│       │   │   │   └── headers.py    # CSP, HSTS, CSRF
│       │   │   └── models.py.jinja
│       │   └── email/                # Jinja templates for all mails
│       ├── tests/
│       └── .github/workflows/ci.yml.jinja
└── tests/                            # CLI tests: generate → run generated test suite
```

---

## 6. Hardening spec — what "protected" means concretely

Every item below is generated code, enabled by default, covered by a test.

**Credentials**
- Argon2id via `pwdlib` (memory 64 MiB, time 3, parallelism 4 — tuned in template)
- Password policy: min 12 chars, HIBP range-API breach check, reject on match
- Constant-time comparison everywhere (`hmac.compare_digest`)

**Tokens & sessions**
- Access token: JWT, 15 min TTL, `aud`/`iss` claims validated
- Refresh token: opaque, 30 day TTL, **rotated on every use**
- **Reuse detection**: replayed refresh token → revoke the entire token family + audit event
- Cookies: `HttpOnly`, `Secure`, `SameSite=Lax` (configurable `Strict`), `__Host-` prefix
- CSRF: double-submit token on all cookie-authenticated mutating routes
- Logout revokes server-side (Redis denylist keyed by `jti`)

**OTP**
- 6 digits from `secrets.randbelow`, never `random`
- Stored as a hash in Redis, not plaintext
- Single-use, 5 min TTL, max 5 verification attempts then burn
- Per-identifier and per-IP send throttle (max 3 / 15 min)
- TOTP 2FA: ±1 step window, replay guard on last-used counter, 10 single-use recovery codes

**Abuse control**
- `slowapi` Redis-backed rate limits, per-route: login 5/min/IP, register 3/hour/IP,
  forgot-password 3/hour/email, OTP send 3/15min
- Progressive account lockout after 5 failures (exponential backoff, not permanent)
- **Uniform response timing + identical messages** on login and forgot-password so the API
  never reveals whether an account exists

**SSO**
- PKCE mandatory, `state` + `nonce` validated, strict `redirect_uri` allowlist
- Reject unverified emails from IdPs; require explicit account-linking confirmation
  (prevents pre-registration account-takeover)

**Operational**
- Secrets only from env — CLI generates a `.env` with `secrets.token_urlsafe(64)` values,
  writes `0600`, and adds it to `.gitignore` before the first commit
- Structured audit log for every auth event (actor, IP, UA, outcome), PII-redacted
- Security headers middleware: HSTS, CSP, `X-Content-Type-Options`, `Referrer-Policy`
- CI runs `bandit`, `pip-audit`, `gitleaks`, `semgrep` — generated workflow fails on findings

---

## 7. CLI surface

```
basivo-auth new <name>          # interactive scaffold (copier run_copy)
  --preset minimal|standard|enterprise
  --features otp,totp,sso,magic-link,passkeys,saml
  --db postgres|sqlite  --defaults  --no-git  --no-install

basivo-auth update              # copier update — pull template fixes into this project
basivo-auth add <feature>       # re-run copier with one more feature enabled
basivo-auth doctor              # verify python/uv/docker/git/xmlsec, .env sanity
basivo-auth secrets rotate      # regenerate JWT/session secrets, print rotation runbook
basivo-auth version
```

**Presets**
- `minimal` — register, login, forgot/reset, verify email
- `standard` — minimal + OTP + TOTP 2FA + Google/GitHub SSO *(default)*
- `enterprise` — standard + generic OIDC + SAML + orgs/roles + audit export

---

## 8. Phases

| Phase | Deliverable | Exit criterion |
|---|---|---|
| **0. Skeleton** | Repo, `pyproject.toml`, Typer CLI with `--version` + `doctor` | `uv tool install git+file://$(pwd)` works, `basivo-auth doctor` passes |
| **1. Copier spine** | `copier.yml`, minimal template, `new` command, post-gen hooks | `basivo-auth new demo` → `docker compose up` → `/health` returns 200 |
| **2. Core auth** | `app/auth/engine/` seam + register/login/logout/me/forgot/reset/verify | Generated `pytest` suite green; ruff banned-import rule enforced |
| **3. Hardening** | Everything in §6 — rate limit, lockout, rotation+reuse detection, audit, headers, CSRF | Abuse tests green: reuse detection revokes family; enumeration timing flat |
| **4. OTP + 2FA** | Email/SMS OTP, TOTP with QR + recovery codes, step-up auth | Replay, expiry, throttle, and attempt-burn tests green |
| **5. SSO** | `httpx-oauth` Google/GitHub/Microsoft + `authlib` generic OIDC, PKCE, safe linking | Full flow tested against a mock IdP; takeover test blocked |
| **6. Update channel** | `basivo-auth update`, template git tags, migration notes in `copier.yml` `_migrations` | Generate at `v0.1.0` → tag `v0.2.0` → `copier update` applies cleanly with local edits preserved |
| **7. Optional plugins** | Magic link, passkeys, SAML, orgs/roles | Each toggles cleanly on/off; SAML gated behind `doctor` xmlsec check |
| **8. Release** | README, `SECURITY.md`, threat model, CI matrix, `v1.0.0` tag | Fresh machine: install from GitHub URL → generate → deploy |

Phases 0–3 are the real product. 4–6 make it complete. 7 is opt-in.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| `fastapi-users` successor lands with a different API | The §2 seam + ruff ban rule. Swap is ~400 lines in one package. |
| `copier update` conflicts pile up as products diverge | Keep template logic-light; ship `_migrations` in `copier.yml`; document `copier recopy` fallback |
| SAML drags in `xmlsec` and breaks Docker builds | Off by default; `doctor` checks the system lib; separate Dockerfile stage |
| Hand-rolled OTP/2FA is where custom auth code usually fails | Every control in §6 has a named test; run `semgrep` auth rulesets in CI |
| Generated projects fall behind on CVEs | Generated CI runs `pip-audit` on a weekly schedule, not just on PR |

---

## 10. First commands

```bash
cd /Users/abu/OtherPythonProjects/basivo-auth
git init && uv init --package --name basivo-auth
uv add typer rich copier
uv tool install --editable .
basivo-auth doctor
```

---

## Sources
- fastapi-users maintenance-mode notice and feature list — https://github.com/fastapi-users/fastapi-users
- fastapi-users 15.0.5 — https://pypi.org/project/fastapi-users/
- Copier update mechanics and `recopy` fallback — https://copier.readthedocs.io/en/stable/updating/
- pwdlib rationale (passlib unmaintained, breaks on Python 3.13) — https://www.fvoron.com/blog/introducing-pwdlib-a-modern-password-hash-helper-for-python/
- fastapi-users password hash config — https://fastapi-users.github.io/fastapi-users/latest/configuration/password-hash/
- PyOTP 2.10.0 — https://pypi.org/project/pyotp/
- Distributing internal Python CLIs with uv — https://pydevtools.com/handbook/how-to/how-to-distribute-internal-python-cli-tools-with-uv/
