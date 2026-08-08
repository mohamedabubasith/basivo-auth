"""Inspect an existing FastAPI project so auth can be installed into it.

Everything here is a *suggestion*. Detection is heuristic — projects lay
themselves out in more ways than any set of rules can cover — so the CLI shows
what it found and lets the user correct it before anything is written. Nothing
is inferred silently.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: Directories that are never the project's own source package.
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        "docs",
        "tests",
        "test",
        "migrations",
        "alembic",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".idea",
        ".vscode",
        "scripts",
        "static",
        "templates",
        "htmlcov",
    }
)

BASE_MARKERS = ("DeclarativeBase", "declarative_base")


@dataclass(slots=True)
class ModuleFacts:
    """The handful of things we look for in one source file."""

    base_names: list[str] = field(default_factory=list)
    session_deps: list[str] = field(default_factory=list)
    fastapi_apps: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HostProject:
    """What we could work out about the project we are installing into."""

    root: Path
    package_dir: Path | None = None
    package_module: str = ""

    db_module: str = ""
    base_name: str = "Base"
    session_dependency: str = ""

    app_module: str = ""
    app_variable: str = "app"

    has_alembic: bool = False
    has_pyproject: bool = False
    uses_src_layout: bool = False

    warnings: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.package_dir is not None

    def module_path(self, path: Path) -> str:
        """Dotted import path for a file inside the project."""
        relative = path.relative_to(self.root).with_suffix("")
        parts = list(relative.parts)
        if self.uses_src_layout and parts and parts[0] == "src":
            parts = parts[1:]
        return ".".join(parts)


def _iter_python_files(root: Path, package: Path) -> list[Path]:
    return [
        path
        for path in sorted(package.rglob("*.py"))
        if not any(part in IGNORED_DIRS for part in path.relative_to(root).parts)
    ]


def _find_package(root: Path) -> tuple[Path | None, bool]:
    """Locate the project's own source package.

    Prefers ``src/<pkg>`` when present, then a top-level directory holding an
    ``__init__.py``. Returns ``(package, uses_src_layout)``.
    """
    src = root / "src"
    if src.is_dir():
        for child in sorted(src.iterdir()):
            if child.is_dir() and (child / "__init__.py").is_file():
                return child, True

    candidates = [
        child
        for child in sorted(root.iterdir())
        if child.is_dir()
        and child.name not in IGNORED_DIRS
        and not child.name.startswith(".")
        and (child / "__init__.py").is_file()
    ]
    if not candidates:
        return None, False

    # A package literally named `app` is the overwhelmingly common FastAPI
    # convention, so prefer it when several candidates exist.
    for candidate in candidates:
        if candidate.name == "app":
            return candidate, False
    return candidates[0], False


def _scan_module(path: Path) -> ModuleFacts:
    """Extract the few facts we need, via AST rather than regex.

    Import aliases, decorators and string contents all make a textual scan
    unreliable; parsing is barely more work and does not produce false hits
    inside comments or docstrings.
    """
    facts = ModuleFacts()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return facts

    for node in ast.walk(tree):
        # class Base(DeclarativeBase)
        if isinstance(node, ast.ClassDef):
            for parent in node.bases:
                name = getattr(parent, "id", None) or getattr(parent, "attr", None)
                if name in BASE_MARKERS:
                    facts.base_names.append(node.name)

        # Base = declarative_base()  /  app = FastAPI()
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if name in BASE_MARKERS:
                    facts.base_names.append(target.id)
                elif name == "FastAPI":
                    facts.fastapi_apps.append(target.id)

        # async def get_session(...) -> AsyncGenerator[AsyncSession, None]
        if isinstance(node, ast.AsyncFunctionDef):
            annotation = ast.unparse(node.returns) if node.returns else ""
            yields_session = "AsyncSession" in ast.unparse(node) and any(
                isinstance(inner, ast.Yield) for inner in ast.walk(node)
            )
            if "AsyncSession" in annotation or yields_session:
                facts.session_deps.append(node.name)

    return facts


def inspect_project(root: Path) -> HostProject:
    """Best-effort read of an existing FastAPI project."""
    root = root.resolve()
    host = HostProject(root=root)

    host.has_pyproject = (root / "pyproject.toml").is_file()
    host.has_alembic = (root / "alembic").is_dir() or (root / "alembic.ini").is_file()

    package, uses_src = _find_package(root)
    host.uses_src_layout = uses_src
    if package is None:
        host.warnings.append(
            "No Python package found (a directory containing __init__.py). "
            "Point --package at it explicitly."
        )
        return host

    host.package_dir = package
    host.package_module = host.module_path(package / "__init__.py").removesuffix(".__init__")

    for path in _iter_python_files(root, package):
        facts = _scan_module(path)
        module = host.module_path(path)

        if facts.base_names and not host.db_module:
            host.db_module = module
            host.base_name = facts.base_names[0]

        # Prefer a session dependency defined alongside the Base.
        if (
            facts.session_deps
            and not host.session_dependency
            and (not host.db_module or module == host.db_module)
        ):
            host.session_dependency = facts.session_deps[0]

        if facts.fastapi_apps and not host.app_module:
            host.app_module = module
            host.app_variable = facts.fastapi_apps[0]

    if not host.db_module:
        host.warnings.append(
            "No SQLAlchemy declarative Base found. Auth needs one to register "
            "its tables on your metadata — pass --db-module explicitly."
        )
    if not host.session_dependency:
        host.warnings.append(
            "No async session dependency found. Auth needs a callable that "
            "yields an AsyncSession — pass --session-dependency explicitly."
        )
    if not host.app_module:
        host.warnings.append("No FastAPI() instance found; wire the router in manually.")
    if not host.has_alembic:
        host.warnings.append(
            "No Alembic setup found. You will need migrations for the auth tables."
        )

    return host


def read_project_name(pyproject: Path) -> str:
    """The project's declared name.

    Used for cookie prefixes and the JWT issuer/audience, so it should be the
    name the project calls itself — not whatever the checkout directory happens
    to be called.
    """
    if not pyproject.is_file():
        return ""
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return ""
    return str((data.get("project") or {}).get("name", ""))


def read_dependencies(pyproject: Path) -> list[str]:
    """Existing runtime dependencies, so a merge can skip what is already there."""
    if not pyproject.is_file():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    project = data.get("project") or {}
    return [str(item) for item in project.get("dependencies", [])]


def requirement_name(requirement: str) -> str:
    """Bare distribution name from a requirement string."""
    for separator in ("[", ">", "<", "=", "!", "~", ";", " "):
        requirement = requirement.split(separator)[0]
    return requirement.strip().lower().replace("_", "-")
