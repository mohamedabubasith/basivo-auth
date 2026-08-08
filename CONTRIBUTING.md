# Contributing

Thanks for looking. This project generates security-critical code, so a few
things here are stricter than you might expect. The rules below are not style
preferences — each one exists because breaking it produced a real bug.

## Getting set up

```bash
git clone https://github.com/mohamedabubasith/basivo-auth
cd basivo-auth
uv sync --all-extras --dev
uv tool install --editable .          # `basivo-auth` now points at your checkout
```

Check it works:

```bash
uv run pytest                          # the generator's own tests
basivo-auth new /tmp/demo --local --defaults
```

`--local` renders your working copy — uncommitted edits included — instead of
fetching from GitHub. You will want it constantly.

(It passes Copier `vcs_ref=HEAD` to do that. Copier resolves a git source to a
committed ref otherwise, which silently renders the last release and makes it
look like your template edit did nothing.)

## How the repo is laid out

```
src/basivo_auth/     the CLI. Ordinary Python, ordinary tests
template/project/    the blueprint. Jinja + Copier
tests/               tests for the CLI *and* contract tests for the template
copier.yml           every question the template can be configured with
```

The distinction that matters: `src/` is a program, `template/` is *text that
becomes a program*. Editing the template is not like editing code — nothing
type-checks it, and a mistake surfaces only in the generated output.

## Testing what you changed

Running `pytest` is not enough. It tests the generator, not what the generator
produces — and every serious bug in this project's history has been in the
output, not the generator.

```bash
# Generate and check a real project
basivo-auth new /tmp/demo --local --defaults --preset enterprise
cd /tmp/demo
uv run ruff check . && uv run mypy app && uv run pytest
```

Two paths behave differently and both need checking:

```bash
--state database     # no Redis: different lockout, OTP and single-use code
--no-install         # skips dependency install, which skips a formatting route
```

CI runs all of this across presets, both state backends, three Terraform
targets, and an embedded install into a host project. If you can, run the
combination your change touches before opening the PR.

## Rules that are enforced

### The engine seam

`fastapi_users` may only be imported inside the generated `engine/` package.
Everything else imports from `app.engine`.

This is checked by a ruff rule, a CI job, and a test in `tests/test_template.py`.
It exists because `fastapi-users` entered maintenance mode in March 2026 — the
seam is what keeps a future migration to ~400 lines in one package instead of a
rewrite. Please do not weaken it "just this once".

### Conditional filenames

```
{% if feature_otp %}otp.py{% endif %}.jinja      correct
{% if feature_otp %}otp{% endif %}.py.jinja      renders a stray ".py" file
```

Everything except the `.jinja` suffix goes **inside** the condition. Get it
wrong and disabling the feature leaves a file literally named `.py` in the
generated project. `tests/test_template.py` catches this.

### Never hand-tune Jinja whitespace

If generated output has the wrong number of blank lines, **do not** adjust
newlines in the template. Jinja's whitespace handling interacts with every
conditional block, so the correct count differs per feature combination — a fix
for one preset breaks another. This was tried; it does not work.

Formatting is normalised mechanically by `postgen.format_code`, which runs
`ruff format` and `ruff check --fix --select I` after every generation. Trust it.

### Rate-limited handlers need `response: Response`

Any handler carrying `@limiter.limit` must declare a `response: Response`
parameter. SlowAPI injects its headers into that argument and raises without it.

The trap: the test suite runs with rate limiting **off**, so a handler missing
it passes every test and then returns 500 on its first production request. Nine
endpoints shipped this way once. `tests/test_ratelimit.py` in the generated
project now checks every router.

### Security changes need a test that encodes the property

Not "the endpoint returns 200" — a test that fails if the *security property*
is lost. Look at
`test_reusing_a_rotated_token_revokes_the_entire_family` for the shape: it
describes an attack, and fails if the attack starts working.

Mark them `@pytest.mark.security`.

## Changing the template's questions

Adding an option means touching three places, and they must agree:

1. `copier.yml` — the question
2. `src/basivo_auth/config.py` — the field on `ProjectAnswers`
3. `src/basivo_auth/cli.py` — the flag, if it should be settable non-interactively

`tests/test_template.py::test_copier_questions_cover_every_answer_key` fails if
they drift apart.

Values `copier.yml` derives itself (`package_module`, `transport_cookie`, …) use
`when: false` and are **not** sent from Python — one source of truth, so they
cannot disagree on update.

## Commits and pull requests

Conventional-ish prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
`chore:`.

Write the body for someone reading it in a year with no context: what was wrong,
why this fix rather than another. Bodies matter more than subjects here, because
`git log` is the only record of why a security control is shaped the way it is.

In the PR, please say which combinations you actually ran. "Tested standard +
enterprise, both state backends" is genuinely useful; CI will confirm the rest.

## Reporting a security issue

Not through a pull request, and not through an issue. See
[SECURITY.md](SECURITY.md).

## Releasing

Maintainers only.

```bash
# 1. bump the version in pyproject.toml
# 2. update CHANGELOG.md
git commit -am "chore: release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --tags
```

Tags are the distribution mechanism: `uv tool install git+…@vX.Y.Z` resolves
them, and `copier update` compares them to work out what changed. A tag that is
moved or deleted breaks updates for every project pinned to it. **Never
force-push a released tag.**
