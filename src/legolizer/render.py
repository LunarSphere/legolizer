"""Render a model with LDView or LPub3D using configured command-line tools."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path


def render_model(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    custom = os.getenv("LPUB3D_RENDER_ARGS")
    lpub = os.getenv("LPUB3D_BIN") or shutil.which("lpub3d") or _app_binary("LPub3D")
    ldview = (
        os.getenv("LDVIEW_BIN")
        or shutil.which("LDView64")
        or shutil.which("LDView")
        or shutil.which("ldview")
        or _app_binary("LDView")
    )
    if custom and lpub:
        args = [
            part.format(input=str(source), output=str(output))
            for part in shlex.split(custom, posix=os.name != "nt")
        ]
        command = [lpub, *args]
    elif ldview:
        ldraw_dir = _ldraw_dir()
        command = [ldview]
        if ldraw_dir:
            command.append(f"-LDrawDir={ldraw_dir}")
        command.extend(
            [
                "-SaveWidth=1200",
                "-SaveHeight=900",
                "-SaveZoomToFit=1",
                "-DefaultZoom=0.85",
                "-cg20,30",
                "-BackgroundColor3=0xFFFFFF",
                "-SaveAlpha=0",
                f"-SaveSnapshot={output.resolve()}",
                str(source.resolve()),
            ]
        )
    elif lpub:
        raise RuntimeError(
            "LPub3D is installed but its release-specific render flags are unknown. "
            "Set LPUB3D_RENDER_ARGS with {input} and {output} placeholders, or set LDVIEW_BIN."
        )
    else:
        raise RuntimeError("Install LDView or LPub3D, or set LDVIEW_BIN / LPUB3D_BIN")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Renderer executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Renderer failed: {exc.stderr.strip() or exc.stdout.strip()}") from exc
    if not output.exists():
        raise RuntimeError(f"Renderer completed but did not create {output}")


def _app_binary(name: str) -> str | None:
    """Find an installed renderer in the standard macOS or Windows install locations."""
    if os.name == "nt":
        roots = [os.getenv(var) for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        # LDView's 64-bit Windows build ships as LDView64.exe.
        executables = [f"{name}64.exe", f"{name}.exe"]
        candidates = [
            Path(root) / folder / exe
            for root in roots
            if root
            for folder in (name, Path("Programs") / name)
            for exe in executables
        ]
    else:
        executable = Path("Contents") / "MacOS" / name
        candidates = [
            app / f"{name}.app" / executable
            for app in (Path("/Applications"), Path.home() / "Applications")
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _ldraw_dir() -> str | None:
    """Get LDView's expected `ldraw` folder from pyldraw3 or an explicit override."""
    override = os.getenv("LDRAW_LIBRARY_PATH")
    if override:
        root = Path(override).expanduser()
    else:
        try:
            from ldraw.config import Config

            root = Path(Config.load().ldraw_library_path)
        except (ImportError, OSError, AttributeError):
            return None
    nested = root / "ldraw"
    return str(nested if nested.is_dir() else root)
