# Security Policy

`basivo-auth` generates authentication code. A flaw here does not stay here — it
is copied into every project generated afterwards, and sits in the one component
whose job is to keep everything else out. Please treat findings accordingly.

## Reporting a vulnerability

**Do not open a public issue.**

Use GitHub's private reporting:
[**Report a vulnerability**](https://github.com/mohamedabubasith/basivo-auth/security/advisories/new)

That creates a private advisory only maintainers can see, with a place to
discuss and coordinate a fix before anything is public.

Useful things to include, as far as you have them:

- which command and options produced the affected code (`new` / `init`, preset,
  features, state backend)
- the file and line in the **generated** project, not the template, if that is
  where the issue lives
- what an attacker gains, and what they need to start with
- a proof of concept, if you have one

You should get an acknowledgement within a few days. If a fix is warranted it
will ship as a tagged release, and the advisory will say which versions are
affected so projects know whether they need to run `basivo-auth update`.

## What counts

This project has two attack surfaces, and the second is the one that matters.

**The generator** — the CLI itself. Template injection, writing outside the
target directory, leaking secrets into logs or into git.

**The generated code** — everything a scaffolded project ships with. This is
the larger surface, because a weakness here is reproduced in every project.
Reports about generated code are in scope even though the vulnerable code lives
in *your* repository rather than this one.

### In scope

- Any way to authenticate as another user, or without credentials
- Token forgery, replay, or a token minted for one purpose being accepted for
  another
- Password hashes recoverable, or stored weaker than the documented Argon2id
  parameters
- Account enumeration through response content, status codes, or **timing**
- Cross-tenant access: reaching another organisation's data with a valid session
- Privilege escalation: acquiring authority the role was not granted
- Bypassing a second factor, lockout, or single-use enforcement on codes and
  links
- Secrets reaching a log, an error response, an audit row, or a git commit
- The generator writing files outside the target directory, or executing
  attacker-controlled template content

### Known and documented, not vulnerabilities

These are deliberate trade-offs, each explained in the generated
`docs/security.md`. Please read that before reporting.

- **Access tokens cannot be revoked before expiry.** That is the cost of
  stateless verification; the lifetime is 15 minutes for exactly this reason.
  Refresh tokens *are* revocable, and a password change invalidates everything.
- **Rate limiting is per-process when `--state database` is used.** Documented,
  and the generated Terraform moves the control to API Gateway and WAF.
- **`--local` projects cannot receive updates.** There is no git history to diff.
- **Lockout is temporary, not permanent.** A permanent lock is a denial-of-service
  weapon: anyone who knows an address could lock its owner out forever.
- **HIBP breach checking fails open by default.** A third party being down should
  not block your registrations. `PASSWORD_BREACH_FAIL_OPEN=false` reverses it.
- **`--no-server-header` is required.** uvicorn adds `Server:` after the ASGI
  app returns, so middleware cannot remove it. The generated Dockerfile passes
  the flag.

## Supported versions

Only the latest tagged release. This is a code generator: fixes reach existing
projects through `basivo-auth update`, not through a dependency bump, so
back-porting to old tags would not help anyone who has already generated.

## For people running generated projects

A fix here does not reach you automatically — your project holds a copy, not a
dependency. When an advisory is published:

```bash
cd your-auth-project
basivo-auth update
git diff            # review before committing
```

Work through the production checklist at the end of your project's
`docs/security.md` before your first deploy. The controls are only as good as
the configuration around them, and `TRUSTED_PROXY_COUNT` in particular defeats
every IP-keyed control in the service if it is wrong.
