"""The template contract.

These assert structural properties of the Copier template that are easy to break
and expensive to notice — a conditional filename that renders to a stray `.py`,
or a missing answers file that silently severs a project from future updates.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from basivo_auth.config import Feature, ProjectAnswers
from basivo_auth.runner import bundled_template_path

TEMPLATE_ROOT = bundled_template_path()
PROJECT_ROOT = TEMPLATE_ROOT / "template" / "project"


@pytest.fixture(scope="module")
def copier_config() -> dict:
    return yaml.safe_load((TEMPLATE_ROOT / "copier.yml").read_text(encoding="utf-8"))


def test_template_is_discoverable() -> None:
    assert (TEMPLATE_ROOT / "copier.yml").is_file()
    assert PROJECT_ROOT.is_dir()


def test_answers_file_template_exists() -> None:
    """Without this, Copier writes no .copier-answers.yml.

    A project generated without it can never run `basivo-auth update`, which
    silently removes the security-patch channel — the whole point of the tool.
    """
    matches = list(PROJECT_ROOT.glob("*_copier_conf.answers_file*"))
    assert matches, "template must contain {{ _copier_conf.answers_file }}.jinja"


def test_subdirectory_matches_the_layout(copier_config: dict) -> None:
    assert copier_config["_subdirectory"] == "template/project"


def test_env_file_is_never_overwritten_on_update(copier_config: dict) -> None:
    """`.env` holds generated secrets; an update must not clobber it."""
    assert ".env" in copier_config.get("_skip_if_exists", [])


def test_every_feature_has_a_copier_question(copier_config: dict) -> None:
    for feature in Feature:
        assert f"feature_{feature.value}" in copier_config


def test_copier_questions_cover_every_answer_key(copier_config: dict) -> None:
    """to_copier() must not send a key copier.yml does not declare."""
    declared = {key for key in copier_config if not key.startswith("_")}
    sent = set(ProjectAnswers(project_slug="acme-auth").to_copier())
    assert sent <= declared, f"undeclared answers: {sorted(sent - declared)}"


CONDITIONAL_NAME = re.compile(r"\{%\s*if\s+(?P<cond>[^%]+?)\s*%\}(?P<body>.*?)\{%\s*endif\s*%\}")


@pytest.mark.parametrize("path", sorted(PROJECT_ROOT.rglob("*")), ids=str)
def test_conditional_filenames_wrap_the_whole_name(path: Path) -> None:
    """The suffix must sit outside the condition, the rest inside.

    `{% if x %}otp{% endif %}.py.jinja` renders to a stray `.py` file when the
    feature is off. The correct form is `{% if x %}otp.py{% endif %}.jinja`,
    which renders to an empty name and is skipped.
    """
    name = path.name
    match = CONDITIONAL_NAME.search(name)
    if match is None:
        return

    remainder = name[match.end() :]
    assert remainder in ("", ".jinja"), (
        f"{path.relative_to(PROJECT_ROOT)}: everything except the .jinja suffix "
        f"must sit inside the condition, but {remainder!r} is outside. "
        f"Use '{{% if x %}}name.py{{% endif %}}.jinja', not "
        f"'{{% if x %}}name{{% endif %}}.py.jinja' — the latter renders to a "
        f"stray '.py' file when the condition is false."
    )


def test_directories_never_carry_the_template_suffix() -> None:
    """Copier renders directory names but must not treat them as templates."""
    for path in PROJECT_ROOT.rglob("*"):
        if path.is_dir():
            assert not path.name.endswith(".jinja"), path


def _read(pattern: str) -> str:
    """Read a template file whose name carries a Jinja condition."""
    matches = list(PROJECT_ROOT.glob(pattern))
    assert matches, f"no template matching {pattern!r}"
    return matches[0].read_text(encoding="utf-8")


def test_engine_seam_is_declared_in_generated_lint_config() -> None:
    config = _read("*pyproject.toml*.jinja")
    assert "flake8-tidy-imports.banned-api" in config
    assert '"fastapi_users".msg' in config
    assert '"{{ package_dir }}/engine/*" = ["TID251"]' in config


def test_only_the_engine_package_imports_fastapi_users() -> None:
    """The same rule the generated CI enforces, checked on the template itself."""
    offenders = []
    for path in PROJECT_ROOT.rglob("*.py*.jinja"):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if "/engine/" in relative or relative.startswith("{{ tests_dir }}"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*(from|import)\s+fastapi_users", line):
                offenders.append(f"{relative}:{number}")
    assert not offenders, f"fastapi_users imported outside the engine: {offenders}"


def test_package_directory_is_parameterised() -> None:
    """One template must serve both install modes.

    A hardcoded `app/` would mean embedded projects could not place the package
    inside their own package, and the two modes would drift into two templates.
    """
    assert (PROJECT_ROOT / "{{ package_dir }}").is_dir()
    assert not (PROJECT_ROOT / "app").exists()


@pytest.mark.parametrize(
    "relative",
    [
        "{% if is_service %}pyproject.toml{% endif %}.jinja",
        "{% if is_service %}alembic{% endif %}",
        "{{ package_dir }}/{% if is_service %}main.py{% endif %}.jinja",
        "{{ package_dir }}/{% if is_embedded %}router.py{% endif %}.jinja",
    ],
)
def test_mode_specific_artefacts_are_gated(relative: str) -> None:
    """Service-only and embedded-only files must carry their mode condition.

    Without the gate an embedded install would drop a pyproject.toml and an
    alembic tree into a project that already has both.
    """
    assert (PROJECT_ROOT / relative).exists(), relative


def test_embedded_db_module_adopts_the_host() -> None:
    """The embedded branch must import the host's Base rather than build one."""
    source = (PROJECT_ROOT / "{{ package_dir }}" / "db.py.jinja").read_text(encoding="utf-8")
    assert "{{ host_db_module }} import {{ host_base_name }} as Base" in source
    assert "{{ host_session_dependency }} as get_async_session" in source
    assert "is_embedded" in source


def test_no_secret_literals_in_the_template() -> None:
    """Secrets are generated at post-gen time and must never live in the repo."""
    pattern = re.compile(
        r"SECRET_KEY\s*[:=]\s*[\"'][^\"'{}\s]{8,}",
    )
    offenders = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # conftest sets deliberately fake values for the test environment.
        if path.name.startswith("conftest") or path.name.startswith("test_"):
            continue
        if pattern.search(text):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, f"hardcoded secret-looking values in: {offenders}"
