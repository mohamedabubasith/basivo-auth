"""Interactive project configuration.

Implemented with Rich + Typer primitives only. A full-screen picker (questionary,
prompt_toolkit) would be prettier but adds a dependency and breaks in non-TTY
contexts such as CI, where ``--defaults`` is used anyway.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from basivo_auth.config import (
    Database,
    EmailProvider,
    Feature,
    Preset,
    ProjectAnswers,
    TokenTransport,
)


def _choose_preset(console: Console) -> Preset:
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("Preset", style="bold")
    table.add_column("Includes")

    presets = list(Preset)
    for index, preset in enumerate(presets, start=1):
        marker = " [green](default)[/green]" if preset is Preset.STANDARD else ""
        table.add_row(str(index), f"{preset.value}{marker}", preset.description)

    console.print(table)
    choice = typer.prompt("Preset", default=str(presets.index(Preset.STANDARD) + 1))
    try:
        return presets[int(choice) - 1]
    except (ValueError, IndexError):
        console.print("[yellow]Unrecognised choice; using 'standard'.[/yellow]")
        return Preset.STANDARD


def _customise_features(console: Console, preset: Preset) -> frozenset[Feature]:
    selected = set(preset.features)

    if not typer.confirm("\nCustomise individual features?", default=False):
        return frozenset(selected)

    features = list(Feature)
    while True:
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("#", style="dim", width=3)
        table.add_column("On", width=3)
        table.add_column("Feature")

        for index, feature in enumerate(features, start=1):
            on = "[green]✓[/green]" if feature in selected else "[dim]·[/dim]"
            table.add_row(str(index), on, feature.label)

        console.print()
        console.print(table)
        raw = typer.prompt(
            "Toggle by number (comma-separated), or press Enter to accept",
            default="",
            show_default=False,
        )
        if not raw.strip():
            break

        for token in raw.split(","):
            token = token.strip()
            if not token.isdigit():
                continue
            position = int(token) - 1
            if 0 <= position < len(features):
                feature = features[position]
                selected.symmetric_difference_update({feature})

    if Feature.SAML in selected:
        console.print(
            "[yellow]SAML needs the system xmlsec1 library; "
            "`basivo-auth doctor` will check for it.[/yellow]"
        )
    return frozenset(selected)


EnumT = TypeVar("EnumT", bound=StrEnum)


def _choose_enum(console: Console, label: str, options: list[EnumT], default: EnumT) -> EnumT:
    rendered = "  ".join(
        f"[bold]{index}[/bold]) {option.value}" + (" [green]*[/green]" if option is default else "")
        for index, option in enumerate(options, start=1)
    )
    console.print(f"\n{label}: {rendered}")
    choice = typer.prompt(label, default=str(options.index(default) + 1))
    try:
        return options[int(choice) - 1]
    except (ValueError, IndexError):
        return default


def interactive(slug: str, console: Console) -> ProjectAnswers:
    console.print(
        Panel.fit(
            f"Configuring [bold cyan]{slug}[/bold cyan]",
            border_style="cyan",
        )
    )

    description = typer.prompt("Short description", default="Authentication service.")
    preset = _choose_preset(console)
    features = _customise_features(console, preset)

    database = _choose_enum(console, "Database", list(Database), Database.POSTGRES)
    transport = _choose_enum(
        console, "Token transport", list(TokenTransport), TokenTransport.COOKIE
    )
    email = _choose_enum(console, "Email provider", list(EmailProvider), EmailProvider.SMTP)

    include_docker = typer.confirm(
        "\nInclude docker-compose (Postgres + Redis + Mailpit)?", default=True
    )
    include_ci = typer.confirm("Include GitHub Actions CI with security scanning?", default=True)

    return ProjectAnswers(
        project_slug=slug,
        project_description=description,
        preset=preset,
        features=features,
        database=database,
        token_transport=transport,
        email_provider=email,
        include_docker=include_docker,
        include_ci=include_ci,
    )
