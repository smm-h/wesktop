"""Cross-platform desktop entry creation and removal for Linux .desktop files, macOS .app bundles, and Windows Start Menu shortcuts."""

from __future__ import annotations

import importlib.util
import logging
import platform
import shutil
import stat
import subprocess
import textwrap
from collections.abc import Sequence
from pathlib import Path, PureWindowsPath

log = logging.getLogger(__name__)


def create_entry(
    name: str,
    command: str,
    *,
    icon: str | Path | None = None,
    comment: str = "",
    categories: str = "Utility;",
) -> Path:
    """Create a platform-native desktop entry. Returns the path of the created entry.

    *command* is a full, already-quoted command line. On Linux/macOS, quote
    arguments with shlex.quote. On Windows, double-quote any path or argument
    containing spaces (see :func:`quote_windows_command`).
    """
    system = platform.system()
    if system == "Linux":
        return _create_linux(name, command, icon=icon, comment=comment, categories=categories)
    elif system == "Darwin":
        return _create_macos(name, command, icon=icon, comment=comment)
    elif system == "Windows":
        return _create_windows(name, command, icon=icon, comment=comment)
    else:
        raise OSError(f"Unsupported platform: {system}")


def remove_entry(name: str) -> bool:
    """Remove a desktop entry (and its launcher script, if any).

    Returns True if something was removed.
    """
    system = platform.system()
    if system == "Linux":
        removed = _remove_linux(name)
    elif system == "Darwin":
        removed = _remove_macos(name)
    elif system == "Windows":
        # Windows shortcuts point directly at their target -- no launcher script.
        return _remove_windows(name)
    else:
        return False
    # Also remove the companion launcher script so it doesn't leak in ~/.local/bin
    if remove_launcher(name):
        removed = True
    return removed


def entry_exists(name: str) -> bool:
    """Check whether a desktop entry already exists for *name* on this platform."""
    system = platform.system()
    if system == "Linux":
        return (_linux_apps_dir() / f"{name}.desktop").exists()
    elif system == "Darwin":
        return (_macos_apps_dir() / f"{name}.app").exists()
    elif system == "Windows":
        return (_windows_start_menu_dir() / f"{name}.lnk").exists()
    return False


# ---------------------------------------------------------------------------
# Launcher scripts (POSIX only)
# ---------------------------------------------------------------------------

def _launcher_dir() -> Path:
    return Path.home() / ".local" / "bin"


def launcher_name(name: str) -> str:
    """Derive the launcher script name for an app: slugged name + '-open'."""
    return name.lower().replace(" ", "-") + "-open"


def launcher_path(name: str) -> Path:
    """Path of the launcher script for *name* (POSIX platforms)."""
    return _launcher_dir() / launcher_name(name)


def create_launcher(name: str, command: str) -> Path:
    """Create an executable launcher script for *name* that execs *command*.

    *command* must be a fully shell-quoted POSIX command line. Only supported
    on Linux and macOS -- a POSIX shell script cannot execute on Windows, so
    Windows shortcuts must point directly at their target instead.
    """
    system = platform.system()
    if system not in ("Linux", "Darwin"):
        raise OSError(
            f"Launcher scripts are not supported on {system}. On Windows, "
            f"point the shortcut directly at the target command instead."
        )
    path = launcher_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nexec {command}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def remove_launcher(name: str) -> bool:
    """Remove the launcher script for *name*. Returns True if it existed."""
    path = launcher_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

def _linux_apps_dir() -> Path:
    return Path.home() / ".local" / "share" / "applications"


def _linux_icons_dir() -> Path:
    return Path.home() / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"


def _create_linux(
    name: str,
    command: str,
    *,
    icon: str | Path | None = None,
    comment: str = "",
    categories: str = "Utility;",
) -> Path:
    apps_dir = _linux_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    icon_value = ""
    if icon is not None:
        icon_path = Path(icon)
        if icon_path.is_file():
            icons_dir = _linux_icons_dir()
            icons_dir.mkdir(parents=True, exist_ok=True)
            dest = icons_dir / f"{name}.png"
            shutil.copy2(icon_path, dest)
            icon_value = str(dest)
        else:
            # Treat as a theme icon name
            icon_value = str(icon)

    # Per the Desktop Entry spec, literal percent signs in Exec must be
    # escaped as %% so they are not parsed as field codes (%U, %f, ...).
    exec_value = command.replace("%", "%%")

    desktop_path = apps_dir / f"{name}.desktop"
    desktop_path.write_text(
        textwrap.dedent(f"""\
            [Desktop Entry]
            Type=Application
            Name={name}
            Exec={exec_value}
            Icon={icon_value}
            Comment={comment}
            Categories={categories}
            Terminal=false
        """)
    )

    # Validate if tool is available
    if shutil.which("desktop-file-validate"):
        result = subprocess.run(
            ["desktop-file-validate", str(desktop_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.warning("desktop-file-validate: %s", result.stderr.strip() or result.stdout.strip())

    # Update database if tool is available
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(apps_dir)],
            capture_output=True,
        )

    return desktop_path


def _remove_linux(name: str) -> bool:
    removed = False
    desktop_path = _linux_apps_dir() / f"{name}.desktop"
    if desktop_path.exists():
        desktop_path.unlink()
        removed = True
    icon_path = _linux_icons_dir() / f"{name}.png"
    if icon_path.exists():
        icon_path.unlink()
        removed = True
    return removed


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

def _macos_apps_dir() -> Path:
    return Path.home() / "Applications"


def _create_macos(
    name: str,
    command: str,
    *,
    icon: str | Path | None = None,
    comment: str = "",
) -> Path:
    bundle_id = "com.wesktop." + name.lower().replace(" ", "-")
    app_dir = _macos_apps_dir() / f"{name}.app"
    contents = app_dir / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Info.plist
    icon_filename = ""
    if icon is not None:
        icon_path = Path(icon)
        if icon_path.is_file():
            dest = resources_dir / "icon.icns"
            shutil.copy2(icon_path, dest)
            icon_filename = "icon"

    plist = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>CFBundleExecutable</key>
            <string>launcher</string>
            <key>CFBundleName</key>
            <string>{name}</string>
            <key>CFBundleIdentifier</key>
            <string>{bundle_id}</string>
            <key>CFBundleVersion</key>
            <string>1.0</string>
            <key>CFBundlePackageType</key>
            <string>APPL</string>
            <key>CFBundleIconFile</key>
            <string>{icon_filename}</string>
            <key>NSHighResolutionCapable</key>
            <true/>
        </dict>
        </plist>
    """)
    (contents / "Info.plist").write_text(plist)

    # Launcher script
    launcher = macos_dir / "launcher"
    launcher.write_text(f"#!/bin/bash\nexec {command}\n")
    launcher.chmod(0o755)

    return app_dir


def _remove_macos(name: str) -> bool:
    app_dir = _macos_apps_dir() / f"{name}.app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
        return True
    return False


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def _windows_start_menu_dir() -> Path:
    import os

    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        raise OSError("APPDATA environment variable not set")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _split_windows_command(command: str) -> tuple[str, str]:
    """Split a Windows command line into (target, arguments).

    Quoting contract: a target path containing spaces MUST be double-quoted,
    e.g. ``'"C:\\Program Files\\app.exe" --arg'``. Unquoted commands split at
    the first whitespace. An unquoted absolute-path target whose first token
    has no file extension is almost certainly a spaces-in-path target
    truncated at the first space -- that is a hard error instead of silently
    producing a shortcut to a nonexistent target.
    """
    command = command.strip()
    if not command:
        raise ValueError("Empty Windows shortcut command")
    if command.startswith('"'):
        end = command.find('"', 1)
        if end == -1:
            raise ValueError(f"Unterminated quote in Windows command: {command!r}")
        target = command[1:end]
        arguments = command[end + 1:].strip()
        return target, arguments
    parts = command.split(None, 1)
    target = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""
    is_abs_path = len(target) >= 3 and target[0].isalpha() and target[1] == ":" and target[2] in "\\/"
    if arguments and is_abs_path and "." not in PureWindowsPath(target).name:
        raise ValueError(
            f"Ambiguous Windows command {command!r}: the target looks like an "
            f"absolute path truncated at a space. Double-quote targets that "
            f"contain spaces, e.g. '\"C:\\Program Files\\app.exe\" --arg'."
        )
    return target, arguments


def quote_windows_command(parts: Sequence[str]) -> str:
    """Join command parts into a Windows command line.

    Follows the quoting contract of :func:`_split_windows_command`: any part
    containing whitespace is double-quoted.
    """
    quoted = []
    for part in parts:
        if '"' in part:
            raise ValueError(
                f"Embedded double quote is not supported in a Windows "
                f"command part: {part!r}"
            )
        quoted.append(f'"{part}"' if (" " in part or "\t" in part) else part)
    return " ".join(quoted)


def _windows_com_available() -> bool:
    """Whether the pywin32 COM backend is importable."""
    return importlib.util.find_spec("win32com") is not None


def _create_windows(
    name: str,
    command: str,
    *,
    icon: str | Path | None = None,
    comment: str = "",
) -> Path:
    start_menu = _windows_start_menu_dir()
    start_menu.mkdir(parents=True, exist_ok=True)
    lnk_path = start_menu / f"{name}.lnk"

    target, arguments = _split_windows_command(command)
    icon_location = str(icon) if icon else ""

    # Explicit backend selection: choose by pywin32 availability up front.
    # Once chosen, a failure is a hard error with the real exception --
    # never silently retried via the other backend.
    if _windows_com_available():
        return _create_windows_com(lnk_path, target, arguments, icon_location, comment)
    return _create_windows_powershell(lnk_path, target, arguments, icon_location, comment)


def _create_windows_com(
    lnk_path: Path,
    target: str,
    arguments: str,
    icon_location: str,
    comment: str,
) -> Path:
    import win32com.client  # type: ignore[import-untyped]

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(lnk_path))
    shortcut.TargetPath = target
    shortcut.Arguments = arguments
    shortcut.Description = comment
    if icon_location:
        shortcut.IconLocation = icon_location
    shortcut.save()
    return lnk_path


def _create_windows_powershell(
    lnk_path: Path,
    target: str,
    arguments: str,
    icon_location: str,
    comment: str,
) -> Path:
    # Escape single quotes for PowerShell strings
    def ps_escape(s: str) -> str:
        return s.replace("'", "''")

    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{ps_escape(str(lnk_path))}'); "
        f"$s.TargetPath = '{ps_escape(target)}'; "
        f"$s.Arguments = '{ps_escape(arguments)}'; "
        f"$s.Description = '{ps_escape(comment)}'; "
    )
    if icon_location:
        script += f"$s.IconLocation = '{ps_escape(icon_location)}'; "
    script += "$s.Save()"

    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
    )
    return lnk_path


def _remove_windows(name: str) -> bool:
    lnk_path = _windows_start_menu_dir() / f"{name}.lnk"
    if lnk_path.exists():
        lnk_path.unlink()
        return True
    return False
