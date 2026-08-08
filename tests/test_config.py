"""Answer model validation and the Copier contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from basivo_auth.config import (
    Database,
    EmailProvider,
    Feature,
    Preset,
    ProjectAnswers,
    TokenTransport,
)


def test_minimal_answers_are_valid() -> None:
    answers = ProjectAnswers(project_slug="acme-auth")
    assert answers.package_name == "acme_auth"
    assert answers.project_name == "Acme Auth"


@pytest.mark.parametrize(
    "slug",
    ["9acme", "acme--auth", "acme-", "-acme", "acme auth", "acme.auth", ""],
)
def test_invalid_slugs_are_rejected(slug: str) -> None:
    with pytest.raises(ValidationError):
        ProjectAnswers(project_slug=slug)


@pytest.mark.parametrize("slug", ["Acme-Auth", "  acme-auth  ", "ACME-AUTH"])
def test_slugs_are_normalised_rather_than_rejected(slug: str) -> None:
    """Case and surrounding whitespace are corrected, not treated as errors."""
    assert ProjectAnswers(project_slug=slug).project_slug == "acme-auth"


@pytest.mark.parametrize("slug", ["app", "tests", "alembic", "auth"])
def test_reserved_slugs_are_rejected(slug: str) -> None:
    """These would shadow a module inside the generated package."""
    with pytest.raises(ValidationError, match="reserved"):
        ProjectAnswers(project_slug=slug)


def test_preset_features_are_applied() -> None:
    answers = ProjectAnswers(project_slug="acme-auth", preset=Preset.STANDARD)
    assert answers.has(Feature.OTP)
    assert answers.has(Feature.TOTP)
    assert answers.has(Feature.SSO)
    assert not answers.has(Feature.SAML)


def test_explicit_features_extend_rather_than_replace_the_preset() -> None:
    answers = ProjectAnswers(
        project_slug="acme-auth",
        preset=Preset.STANDARD,
        features=frozenset({Feature.PASSKEYS}),
    )
    assert answers.has(Feature.PASSKEYS)
    assert answers.has(Feature.OTP), "preset features must survive"


def test_minimal_preset_enables_nothing() -> None:
    answers = ProjectAnswers(project_slug="acme-auth", preset=Preset.MINIMAL)
    assert answers.features == frozenset()


def test_enterprise_preset_includes_authorization() -> None:
    """The preset advertises multi-tenant authz, so orgs must actually be on."""
    answers = ProjectAnswers(project_slug="acme-auth", preset=Preset.ENTERPRISE)
    assert answers.has(Feature.ORGS)


def test_unsupported_python_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unsupported Python"):
        ProjectAnswers(project_slug="acme-auth", python_version="3.9")


def test_access_token_ttl_is_bounded() -> None:
    """A long-lived access token cannot be revoked before it expires."""
    with pytest.raises(ValidationError):
        ProjectAnswers(project_slug="acme-auth", access_token_ttl_seconds=86_400)


class TestCopierContract:
    """`to_copier` output is what the template renders against."""

    def test_every_feature_becomes_a_boolean(self) -> None:
        answers = ProjectAnswers(project_slug="acme-auth", preset=Preset.MINIMAL)
        data = answers.to_copier()
        for feature in Feature:
            key = f"feature_{feature.value}"
            assert key in data, f"{key} missing"
            assert isinstance(data[key], bool)

    def test_derived_values_are_left_to_copier(self) -> None:
        """copier.yml computes these with `when: false`.

        Sending them too would give two sources of truth that could drift on
        update, so they are deliberately absent.
        """
        data = ProjectAnswers(project_slug="acme-auth").to_copier()
        for derived in ("package_name", "database_driver", "transport_cookie", "transport_bearer"):
            assert derived not in data

    def test_enum_values_are_serialised_as_strings(self) -> None:
        data = ProjectAnswers(
            project_slug="acme-auth",
            database=Database.SQLITE,
            token_transport=TokenTransport.BEARER,
            email_provider=EmailProvider.RESEND,
        ).to_copier()
        assert data["database"] == "sqlite"
        assert data["token_transport"] == "bearer"  # noqa: S105 - a transport name
        assert data["email_provider"] == "resend"
        assert data["preset"] == "standard"

    def test_answers_are_json_serialisable(self) -> None:
        """Copier writes these into .copier-answers.yml."""
        import json

        json.dumps(ProjectAnswers(project_slug="acme-auth").to_copier())


def test_transport_flags() -> None:
    assert TokenTransport.BOTH.has_cookie and TokenTransport.BOTH.has_bearer
    assert TokenTransport.COOKIE.has_cookie and not TokenTransport.COOKIE.has_bearer
    assert TokenTransport.BEARER.has_bearer and not TokenTransport.BEARER.has_cookie


def test_answers_are_immutable() -> None:
    """Frozen so a post-validation mutation cannot desync from to_copier()."""
    answers = ProjectAnswers(project_slug="acme-auth")
    with pytest.raises(ValidationError):
        answers.project_slug = "other"  # type: ignore[misc]
