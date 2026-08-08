## What this changes

<!-- And why. If it fixes an issue, link it. -->

## What you ran

<!-- CI covers the matrix, but say what you checked locally. -->

- [ ] `uv run pytest` (the generator's own tests)
- [ ] Generated a project and ran its `ruff` / `mypy` / `pytest`
- [ ] Checked `--state database` (if the change touches lockout, OTP or magic links)
- [ ] Checked `--no-install` (if the change touches generated formatting)
- [ ] `terraform validate` (if the change touches `terraform/`)

Combinations tested:

## If this touches security

- [ ] There is a test that fails if the security property is lost — not just
      one asserting a status code
- [ ] `docs/security.md` in the template says what changed and why
- [ ] The engine seam still holds (`fastapi_users` only inside `engine/`)

## If this adds a template option

- [ ] Declared in `copier.yml`
- [ ] Added to `ProjectAnswers` in `config.py`
- [ ] Exposed as a CLI flag, if it should be settable non-interactively
- [ ] Derived values use `when: false` rather than being sent from Python
