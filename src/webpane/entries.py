"""Cross-platform desktop entry creation and removal."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)


def create_entry(
    name: str,
    command: str,
    *,
    icon: str | Path | None = None,
    comment: str = "",
    categories: str = "Utility;",
) -> Path:
    """Create a platform-native desktop entry. Returns the path of the created entry."""
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
    """Remove a desktop entry. Returns True if something was removed."""
    system = platform.system()
    if system == "Linux":
        return _remove_linux(name)
    elif system == "Darwin":
        return _remove_macos(name)
    elif system == "Windows":
        return _remove_windows(name)
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

    desktop_path = apps_dir / f"{name}.desktop"
    desktop_path.write_text(
        textwrap.dedent(f"""\
            [Desktop Entry]
            Type=Application
            Name={name}
            Exec={command}
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
    bundle_id = "com.webpane." + name.lower().replace(" ", "-")
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

    # Split command into target and arguments
    parts = command.split(None, 1)
    target = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""

    icon_location = str(icon) if icon else ""

    try:
        return _create_windows_com(lnk_path, target, arguments, icon_location, comment)
    except Exception:
        log.debug("win32com unavailable, falling back to PowerShell")
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
