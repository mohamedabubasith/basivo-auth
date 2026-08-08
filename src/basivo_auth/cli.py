"""``basivo-auth`` command line interface."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from basivo_auth import __version__, detect, doctor, embed, postgen, prompts, runner
from basivo_auth.config import (
    Database,
    DeployTarget,
    EmailProvider,
    Feature,
    InstallMode,
    Preset,
    ProjectAnswers,
    StateBackend,
    TokenTransport,
)


class ConflictStyle(StrEnum):
    """How `copier update` marks conflicts it cannot resolve."""

    INLINE = "inline"
    """Git-style <<<<<<< markers written into the file."""

    REJ = "rej"
    """Leave the file untouched and write a sibling .rej patch."""


app = typer.Typer(
    name="basivo-auth",
    help="Scaffold production-hardened FastAPI authentication services.",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
secrets_app = typer.Typer(help="Manage generated project secrets.", no_args_is_help=True)
app.add_typer(secrets_app, name="secrets")

console = Console()
err_console = Console(stderr=True)

STATUS_STYLE = {
    doctor.Status.OK: "[green]✓[/green]",
    doctor.Status.WARN: "[yellow]![/yellow]",
    doctor.Status.FAIL: "[red]✗[/red]",
}


def _fail(message: str, code: int = 1) -> None:
    err_console.print(f"[bold red]error[/bold red] {message}")
    raise typer.Exit(code)


def _render_checks(checks: list[doctor.Check]) -> None:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=2)
    table.add_column(style="bold", width=10)
    table.add_column()
    for check in checks:
        table.add_row(STATUS_STYLE[check.status], check.name, check.detail)
    console.print(table)

    for check in checks:
        if check.status is not doctor.Status.OK and check.remedy:
            console.print(f"  [dim]{check.name}:[/dim] {check.remedy}")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"basivo-auth {__version__}")
        raise typer.Exit


@app.callback()
def main(
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Scaffold and maintain FastAPI authentication services."""


@app.command()
def new(
    slug: Annotated[str, typer.Argument(help="Project slug, e.g. 'acme-auth'.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Parent directory. Defaults to the cwd."),
    ] = None,
    preset: Annotated[Preset | None, typer.Option("--preset", "-p", help="Feature preset.")] = None,
    features: Annotated[
        str | None,
        typer.Option(
            "--features",
            "-f",
            help="Comma-separated features to add on top of the preset "
            "(otp, totp, magic_link, sso, passkeys, saml, orgs).",
        ),
    ] = None,
    database: Annotated[Database | None, typer.Option("--db", help="Database backend.")] = None,
    transport: Annotated[
        TokenTransport | None, typer.Option("--transport", help="Access token transport.")
    ] = None,
    email: Annotated[
        EmailProvider | None, typer.Option("--email", help="Email delivery provider.")
    ] = None,
    python_version: Annotated[str, typer.Option("--python", help="Target Python.")] = "3.12",
    defaults: Annotated[
        bool, typer.Option("--defaults", "-y", help="Skip prompts and accept defaults.")
    ] = False,
    no_git: Annotated[bool, typer.Option("--no-git", help="Skip git init.")] = False,
    no_install: Annotated[bool, typer.Option("--no-install", help="Skip `uv sync`.")] = False,
    no_docker: Annotated[
        bool,
        typer.Option("--no-docker", help="Skip Dockerfile and docker-compose."),
    ] = False,
    no_ci: Annotated[
        bool, typer.Option("--no-ci", help="Skip the GitHub Actions workflow.")
    ] = False,
    no_admin_cli: Annotated[
        bool, typer.Option("--no-admin-cli", help="Skip the operator CLI.")
    ] = False,
    deploy: Annotated[
        DeployTarget | None,
        typer.Option(
            "--deploy",
            help="Generate Terraform for an AWS runtime (ecs, lambda, both).",
        ),
    ] = None,
    state_backend: Annotated[
        StateBackend | None,
        typer.Option(
            "--state",
            help="Where lockout/OTP state lives: redis (default) or database "
            "(no Redis to run, but rate limiting moves to the edge).",
        ),
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Render into a non-empty directory.")
    ] = False,
    template: Annotated[
        str | None,
        typer.Option("--template", help="Override the template source (path or git URL)."),
    ] = None,
    local: Annotated[
        bool,
        typer.Option(
            "--local",
            help="Use the template bundled in this install instead of fetching the git "
            "URL. Works offline, but the generated project cannot `basivo-auth update`.",
        ),
    ] = False,
    vcs_ref: Annotated[
        str | None, typer.Option("--ref", help="Template git ref. Defaults to the latest tag.")
    ] = None,
) -> None:
    """Generate a new authentication service."""
    non_interactive = defaults or not sys.stdin.isatty()

    try:
        if non_interactive:
            selected = set(preset.features) if preset else set(Preset.STANDARD.features)
            if features:
                selected |= _parse_features(features)
            answers = ProjectAnswers(
                project_slug=slug,
                preset=preset or Preset.STANDARD,
                features=frozenset(selected),
                database=database or Database.POSTGRES,
                token_transport=transport or TokenTransport.COOKIE,
                email_provider=email or EmailProvider.SMTP,
                python_version=python_version,
                include_docker=not no_docker,
                include_ci=not no_ci,
                include_admin_cli=not no_admin_cli,
                deploy_target=deploy or DeployTarget.NONE,
                state_backend=state_backend or StateBackend.REDIS,
            )
        else:
            # Validate the slug before spending the user's time on prompts.
            ProjectAnswers(project_slug=slug)
            answers = prompts.interactive(slug, console)
    except ValidationError as exc:
        _fail(_format_validation_error(exc))
        return

    checks = doctor.run_checks(include_saml=answers.has(Feature.SAML))
    failures = list(doctor.blocking_failures(checks))
    if failures:
        err_console.print("[bold red]Environment is not ready:[/bold red]")
        _render_checks(checks)
        raise typer.Exit(1)

    destination = (output or Path.cwd()) / answers.project_slug

    source = runner.resolve_template(template, local=local)
    console.print(f"[dim]template:[/dim] {source}")

    try:
        with console.status("[cyan]Rendering project…[/cyan]"):
            runner.generate(
                answers,
                destination,
                template=template,
                local=local,
                vcs_ref=vcs_ref,
                overwrite=overwrite,
            )
    except (runner.GenerationError, runner.TemplateNotFoundError) as exc:
        _fail(str(exc))
        return

    with console.status("[cyan]Configuring project…[/cyan]"):
        report = postgen.run_all(
            destination,
            answers,
            do_git=not no_git,
            do_install=not no_install,
        )

    if local:
        report.warnings.append(
            "Generated from the bundled template (--local): `basivo-auth update` "
            "will not work here because there is no git history to diff against."
        )

    _render_success(answers, destination, report)


def _parse_features(raw: str) -> set[Feature]:
    parsed: set[Feature] = set()
    valid = {feature.value for feature in Feature}
    for token in raw.split(","):
        name = token.strip().lower().replace("-", "_")
        if not name:
            continue
        if name not in valid:
            _fail(f"Unknown feature {name!r}. Valid: {', '.join(sorted(valid))}.")
        parsed.add(Feature(name))
    return parsed


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'input'}: {error['msg']}"
        for error in exc.errors()
    )


def _render_success(
    answers: ProjectAnswers, destination: Path, report: postgen.PostGenReport
) -> None:
    enabled = sorted(feature.value for feature in answers.features) or ["core auth only"]

    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("path", str(destination))
    summary.add_row("preset", answers.preset.value)
    summary.add_row("features", ", ".join(enabled))
    summary.add_row("database", answers.database.value)
    summary.add_row("transport", answers.token_transport.value)
    summary.add_row("secrets", "generated in .env (0600)" if report.secrets_written else "skipped")
    summary.add_row(
        "git",
        f"initialised @ {report.initial_commit}" if report.initial_commit else "not initialised",
    )
    summary.add_row("deps", "installed" if report.dependencies_installed else "not installed")
    if answers.deploy_target is not DeployTarget.NONE:
        summary.add_row("terraform", f"{answers.deploy_target.value} (see terraform/)")
    if not answers.uses_redis:
        summary.add_row("state", "database (no Redis; rate limiting at the edge)")

    console.print()
    console.print(
        Panel(summary, title="[bold green]Project created[/bold green]", border_style="green")
    )

    for warning in report.warnings:
        console.print(f"[yellow]warning[/yellow] {warning}")

    steps = [f"cd {destination.name}"]
    if answers.include_docker:
        steps.append("docker compose up -d      # Postgres + Redis + Mailpit")
    if not report.dependencies_installed:
        steps.append("uv sync")
    steps += [
        "uv run alembic upgrade head",
        "uv run pytest",
        "uv run fastapi dev app/main.py",
    ]
    console.print("\n[bold]Next:[/bold]")
    console.print(Syntax("\n".join(steps), "bash", theme="ansi_dark", background_color="default"))
    console.print(
        "\n[dim]Later, pull template security fixes into this project with "
        "[/dim][bold]basivo-auth update[/bold][dim].[/dim]"
    )


@app.command()
def init(
    path: Annotated[
        Path | None, typer.Option("--path", help="Project root. Defaults to the cwd.")
    ] = None,
    into: Annotated[
        str | None,
        typer.Option(
            "--into",
            help="Where the auth package goes, e.g. 'app/auth'. Detected if omitted.",
        ),
    ] = None,
    db_module: Annotated[
        str | None,
        typer.Option("--db-module", help="Module holding your SQLAlchemy Base."),
    ] = None,
    base_name: Annotated[
        str | None, typer.Option("--base", help="Name of your declarative Base class.")
    ] = None,
    session_dependency: Annotated[
        str | None,
        typer.Option("--session-dependency", help="Your AsyncSession dependency callable."),
    ] = None,
    preset: Annotated[Preset | None, typer.Option("--preset", "-p")] = None,
    features: Annotated[str | None, typer.Option("--features", "-f")] = None,
    transport: Annotated[TokenTransport | None, typer.Option("--transport")] = None,
    email: Annotated[EmailProvider | None, typer.Option("--email")] = None,
    database: Annotated[Database | None, typer.Option("--db")] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Accept detected values without prompting.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would change, write nothing.")
    ] = False,
    template: Annotated[str | None, typer.Option("--template")] = None,
    local: Annotated[bool, typer.Option("--local")] = False,
) -> None:
    """Install auth into an existing FastAPI project.

    Generates an auth package inside your project that uses **your** database:
    your declarative Base, your session dependency, your migrations. No second
    engine, no second connection pool, and your own tables can foreign-key to
    `user`.

    Nothing is overwritten. Dependencies are appended to your pyproject, auth
    settings are appended to your .env, and the lines to wire into your FastAPI
    app are printed for you to paste.
    """
    project_root = (path or Path.cwd()).resolve()
    host = detect.inspect_project(project_root)

    console.print(
        Panel.fit(
            f"Installing auth into [bold cyan]{project_root.name}[/bold cyan]",
            border_style="cyan",
        )
    )
    _render_host(host)

    detected_package = host.package_module.replace(".", "/")
    package_dir = into or (f"{detected_package}/auth" if detected_package else "auth")
    resolved_db_module = db_module or host.db_module
    resolved_base = base_name or host.base_name
    resolved_session = session_dependency or host.session_dependency

    if not yes and sys.stdin.isatty():
        package_dir = typer.prompt("\nAuth package location", default=package_dir)
        resolved_db_module = typer.prompt(
            "Module with your Base", default=resolved_db_module or "app.db"
        )
        resolved_base = typer.prompt("Declarative Base class", default=resolved_base or "Base")
        resolved_session = typer.prompt(
            "Async session dependency", default=resolved_session or "get_async_session"
        )

    if not resolved_db_module or not resolved_session:
        _fail(
            "Auth needs your SQLAlchemy Base and session dependency. "
            "Pass --db-module and --session-dependency."
        )
        return

    selected = set(preset.features) if preset else set(Preset.STANDARD.features)
    if features:
        selected |= _parse_features(features)

    try:
        answers = ProjectAnswers(
            project_slug=_slugify(
                detect.read_project_name(project_root / "pyproject.toml") or project_root.name
            ),
            install_mode=InstallMode.EMBEDDED,
            package_dir=package_dir,
            tests_dir="tests/auth",
            host_db_module=resolved_db_module,
            host_base_name=resolved_base,
            host_session_dependency=resolved_session,
            preset=preset or Preset.STANDARD,
            features=frozenset(selected),
            database=database or Database.POSTGRES,
            token_transport=transport or TokenTransport.COOKIE,
            email_provider=email or EmailProvider.SMTP,
            include_docker=False,
            include_ci=False,
            include_admin_cli=False,
        )
    except ValidationError as exc:
        _fail(_format_validation_error(exc))
        return

    target = project_root / package_dir
    if target.exists() and any(target.iterdir()):
        _fail(f"{package_dir} already exists and is not empty. Use `basivo-auth update` instead.")
        return

    if dry_run:
        _render_dry_run(answers, project_root, package_dir, host)
        return

    try:
        runner.generate(answers, project_root, template=template, local=local, overwrite=True)
    except (runner.GenerationError, runner.TemplateNotFoundError) as exc:
        _fail(str(exc))
        return

    report = embed.EmbedReport()
    embed.ensure_gitignored(project_root, report)
    embed.merge_dependencies(project_root, answers, report)
    embed.merge_env(project_root, answers, report)

    _render_embed_result(answers, package_dir, host, report)


def _slugify(name: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in name.strip().lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"app-{cleaned}" if cleaned else "app"
    return cleaned


def _render_host(host: detect.HostProject) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("package", host.package_module or "[yellow]not found[/yellow]")
    base = f"{host.db_module}.{host.base_name}" if host.db_module else "[yellow]not found[/yellow]"
    table.add_row("Base", base)
    table.add_row("session dep", host.session_dependency or "[yellow]not found[/yellow]")
    fastapi_app = (
        f"{host.app_module}:{host.app_variable}"
        if host.app_module
        else "[yellow]not found[/yellow]"
    )
    table.add_row("FastAPI app", fastapi_app)
    table.add_row("alembic", "yes" if host.has_alembic else "[yellow]no[/yellow]")
    console.print(table)

    for warning in host.warnings:
        console.print(f"[yellow]![/yellow] {warning}")


def _render_dry_run(
    answers: ProjectAnswers,
    project_root: Path,
    package_dir: str,
    host: detect.HostProject,
) -> None:
    console.print("\n[bold]Would create[/bold]")
    console.print(f"  {package_dir + '/':<24} the auth package")
    console.print(f"  {'tests/auth/':<24} its test suite")

    console.print("\n[bold]Would append to pyproject.toml[/bold]")
    existing = {
        detect.requirement_name(item)
        for item in detect.read_dependencies(project_root / "pyproject.toml")
    }
    for requirement in embed.required_packages(answers):
        already = detect.requirement_name(requirement) in existing
        marker = "[dim]·[/dim]" if already else "[green]+[/green]"
        suffix = " [dim](already present)[/dim]" if already else ""
        # escape(): requirement extras like `[sqlalchemy]` are otherwise eaten
        # by Rich as markup, so the preview would not match what gets written.
        console.print(f"  {marker} {escape(requirement)}{suffix}")

    console.print("\n[bold]Would append to .env[/bold]  (secrets generated locally)")
    console.print("  [dim]DATABASE_URL is left alone — auth shares your database.[/dim]")
    console.print("\n[dim]Nothing was written. Drop --dry-run to apply.[/dim]")


def _render_embed_result(
    answers: ProjectAnswers,
    package_dir: str,
    host: detect.HostProject,
    report: embed.EmbedReport,
) -> None:
    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("package", package_dir)
    summary.add_row("tests", "tests/auth")
    summary.add_row("database", f"shares {answers.host_db_module}.{answers.host_base_name}")
    summary.add_row(
        "features", ", ".join(sorted(f.value for f in answers.features)) or "core auth only"
    )
    summary.add_row(
        "dependencies",
        f"{len(report.added_requirements)} added, "
        f"{len(report.skipped_requirements)} already present",
    )
    summary.add_row("env", f"{len(report.env_keys_added)} keys appended to .env")

    console.print()
    console.print(
        Panel(summary, title="[bold green]Auth installed[/bold green]", border_style="green")
    )

    for warning in report.warnings:
        console.print(f"[yellow]![/yellow] {escape(warning)}")

    console.print("\n[bold]Next[/bold]")
    steps = embed.build_manual_steps(answers, host.app_module, host.app_variable, host.has_alembic)
    for index, step in enumerate(steps, start=1):
        console.print(f"  [cyan]{index}.[/cyan] {step}")

    console.print(
        "\n[dim]Auth owns only "
        f"{package_dir}/ and tests/auth/. `basivo-auth update` refreshes those "
        "and leaves the rest of your project alone.[/dim]"
    )


@app.command()
def update(
    path: Annotated[
        Path | None, typer.Option("--path", help="Project directory. Defaults to the cwd.")
    ] = None,
    ref: Annotated[
        str | None, typer.Option("--ref", help="Template ref to update to. Defaults to latest tag.")
    ] = None,
    conflict: Annotated[
        ConflictStyle, typer.Option("--conflict", help="How to mark update conflicts.")
    ] = ConflictStyle.INLINE,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show changes without writing.")
    ] = False,
) -> None:
    """Pull template updates into an existing project.

    This is the security patch channel: fix once in the template, tag a release,
    then run this in every generated product.
    """
    try:
        target = runner.find_update_target(path or Path.cwd())
    except runner.GenerationError as exc:
        _fail(str(exc))
        return

    console.print(f"Updating [bold cyan]{target.path.name}[/bold cyan] from its template…")
    try:
        runner.update(
            target.path,
            vcs_ref=ref,
            conflict=conflict.value,
            pretend=dry_run,
            quiet=False,
        )
    except runner.GenerationError as exc:
        _fail(str(exc))
        return

    if dry_run:
        console.print("[dim]Dry run: nothing written.[/dim]")
    else:
        console.print("[green]✓[/green] Update applied. Review with `git diff` before committing.")


@app.command()
def add(
    feature: Annotated[Feature, typer.Argument(help="Feature to enable.")],
    path: Annotated[
        Path | None, typer.Option("--path", help="Project directory. Defaults to the cwd.")
    ] = None,
) -> None:
    """Enable an additional feature in an existing project."""
    try:
        target = runner.find_update_target(path or Path.cwd())
    except runner.GenerationError as exc:
        _fail(str(exc))
        return

    if feature is Feature.SAML:
        check = doctor.check_xmlsec()
        if check.status is not doctor.Status.OK:
            console.print(f"[yellow]![/yellow] {check.detail} — {check.remedy}")
            if not typer.confirm("Continue anyway?", default=False):
                raise typer.Exit(1)

    console.print(f"Enabling [bold cyan]{feature.value}[/bold cyan] in {target.path.name}…")
    try:
        runner.update(
            target.path,
            overrides={f"feature_{feature.value}": True},
            quiet=False,
        )
    except runner.GenerationError as exc:
        _fail(str(exc))
        return

    console.print(
        f"[green]✓[/green] {feature.value} enabled. "
        "Run `uv sync` and `uv run alembic upgrade head`, then review `git diff`."
    )


@app.command(name="doctor")
def doctor_command(
    saml: Annotated[bool, typer.Option("--saml", help="Also check SAML prerequisites.")] = False,
) -> None:
    """Verify the local environment can build generated projects."""
    checks = doctor.run_checks(include_saml=saml)
    _render_checks(checks)

    failures = list(doctor.blocking_failures(checks))
    if failures:
        err_console.print(f"\n[bold red]{len(failures)} blocking issue(s).[/bold red]")
        raise typer.Exit(1)
    console.print("\n[green]Environment is ready.[/green]")


@secrets_app.command("rotate")
def secrets_rotate(
    path: Annotated[
        Path | None, typer.Option("--path", help="Project directory. Defaults to the cwd.")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Regenerate every secret in a project's .env."""
    project = (path or Path.cwd()).resolve()

    console.print(
        Panel(
            "Rotating these secrets [bold]invalidates every issued token[/bold]:\n"
            "  • all access tokens stop verifying immediately\n"
            "  • all refresh tokens become unusable — every user is logged out\n"
            "  • pending password-reset and email-verification links break\n\n"
            "For zero-downtime rotation, run both old and new keys through a\n"
            "verification key set first. See docs/security.md in the project.",
            title="[yellow]Impact[/yellow]",
            border_style="yellow",
        )
    )
    if not yes and not typer.confirm("Rotate now?", default=False):
        raise typer.Exit(1)

    try:
        rotated = postgen.rotate_secrets(project)
    except FileNotFoundError as exc:
        _fail(str(exc))
        return

    console.print(f"[green]✓[/green] Rotated: {', '.join(rotated)}")
    console.print("[dim]Restart the service to pick up the new values.[/dim]")


if __name__ == "__main__":  # pragma: no cover
    app()
