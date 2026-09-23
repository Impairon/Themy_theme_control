"""Safe installation of Git-backed Themy modules."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import ast
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    tomllib = None


class ModuleInstallError(RuntimeError):
    """A repository could not be installed as a Themy module."""


def read_module_metadata(path: Path) -> dict:
    if tomllib is not None:
        try:
            with path.open("rb") as handle:
                value = tomllib.load(handle)
        except (OSError, ValueError) as exc:
            raise ModuleInstallError(f"Invalid module.conf: {exc}") from exc
        return value if isinstance(value, dict) else {}

    # The bundled module.conf files use a deliberately small TOML subset.
    # Keep that subset working on Python versions without stdlib tomllib.
    value = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"line {number}: expected key = value")
            key, raw = (part.strip() for part in line.split("=", 1))
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                raise ValueError(f"line {number}: invalid key")
            try:
                value[key] = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                value[key] = raw
    except (OSError, ValueError) as exc:
        raise ModuleInstallError(f"Invalid module.conf: {exc}") from exc
    return value if isinstance(value, dict) else {}


def module_name_from_repo(repo: str) -> str:
    value = repo.strip().rstrip("/")
    if not value:
        raise ModuleInstallError("The repository URL is empty.")

    parsed = urlparse(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value
    name = Path(path.rstrip("/")).name
    if name.endswith(".git"):
        name = name[:-4]
    if not name or name in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ModuleInstallError("Could not determine a safe module name from that repository.")
    return name


def validate_module_directory(path: Path) -> None:
    required = ("module.conf", "render", "apply")
    if not all((path / item).is_file() for item in required):
        raise ModuleInstallError(
            "The repository must contain module.conf plus render and apply files."
        )
    if not os.access(path / "render", os.X_OK) or not os.access(path / "apply", os.X_OK):
        raise ModuleInstallError(
            "The repository's render and apply files must be executable."
        )
    read_module_metadata(path / "module.conf")


def install_module(repo: str, modules_dir: Path, timeout: int = 300) -> Path:
    """Clone and validate one module, removing partial installs on failure."""
    name = module_name_from_repo(repo)
    modules_dir = modules_dir.expanduser()
    if not modules_dir.is_absolute():
        raise ModuleInstallError(f"Module directory must be absolute: {modules_dir}")
    modules_dir.mkdir(parents=True, exist_ok=True)
    target = modules_dir / name
    if target.exists():
        raise ModuleInstallError(f"A module already exists at:\n{target}")

    try:
        result = subprocess.run(
            ["git", "clone", "--", repo.strip(), str(target)],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise ModuleInstallError(str(exc)) from exc

    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        details = (result.stderr or result.stdout or "Git could not clone this repository.").strip()
        raise ModuleInstallError(details[-5000:])

    try:
        validate_module_directory(target)
    except ModuleInstallError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target