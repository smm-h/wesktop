from __future__ import annotations

import platform
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from wesktop.entries import create_entry, remove_entry


# ---------------------------------------------------------------------------
# Linux tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(platform.system() != "Linux", reason="Linux only")
class TestLinux:
    def test_create_desktop_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify .desktop file is created at the correct path."""
        apps_dir = tmp_path / "applications"
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: apps_dir)
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")

        path = create_entry("TestApp", "/usr/bin/test-app")
        assert path == apps_dir / "TestApp.desktop"
        assert path.exists()

    def test_create_desktop_file_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parse .desktop file and verify all fields."""
        apps_dir = tmp_path / "applications"
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: apps_dir)
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")

        path = create_entry(
            "MyApp",
            "/usr/bin/my-app --flag",
            comment="A test app",
            categories="Development;IDE;",
        )
        content = path.read_text()

        assert "[Desktop Entry]" in content
        assert "Type=Application" in content
        assert "Name=MyApp" in content
        assert "Exec=/usr/bin/my-app --flag" in content
        assert "Comment=A test app" in content
        assert "Categories=Development;IDE;" in content
        assert "Terminal=false" in content

    def test_create_with_icon(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify icon is copied to the icons directory."""
        apps_dir = tmp_path / "applications"
        icons_dir = tmp_path / "icons"
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: apps_dir)
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: icons_dir)

        # Create a fake icon file
        icon_src = tmp_path / "source_icon.png"
        icon_src.write_bytes(b"\x89PNG fake icon data")

        path = create_entry("IconApp", "/usr/bin/icon-app", icon=icon_src)

        # Icon should be copied
        icon_dest = icons_dir / "IconApp.png"
        assert icon_dest.exists()
        assert icon_dest.read_bytes() == b"\x89PNG fake icon data"

        # .desktop file should reference the copied icon
        content = path.read_text()
        assert f"Icon={icon_dest}" in content

    def test_create_with_theme_icon_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When icon is a name (not a file), use it directly."""
        apps_dir = tmp_path / "applications"
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: apps_dir)
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")

        path = create_entry("ThemeApp", "/usr/bin/theme-app", icon="utilities-terminal")
        content = path.read_text()
        assert "Icon=utilities-terminal" in content

    def test_remove(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify desktop file and icon are deleted."""
        apps_dir = tmp_path / "applications"
        icons_dir = tmp_path / "icons"
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: apps_dir)
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: icons_dir)

        # Create an icon file
        icon_src = tmp_path / "icon.png"
        icon_src.write_bytes(b"icon")

        create_entry("RmApp", "/usr/bin/rm-app", icon=icon_src)
        assert (apps_dir / "RmApp.desktop").exists()
        assert (icons_dir / "RmApp.png").exists()

        result = remove_entry("RmApp")
        assert result is True
        assert not (apps_dir / "RmApp.desktop").exists()
        assert not (icons_dir / "RmApp.png").exists()

    def test_remove_nonexistent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Removing a nonexistent entry returns False."""
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: tmp_path / "applications")
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")

        result = remove_entry("DoesNotExist")
        assert result is False


# ---------------------------------------------------------------------------
# macOS tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
class TestMacOS:
    def test_create_app_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify .app bundle structure."""
        monkeypatch.setattr("wesktop.entries._macos_apps_dir", lambda: tmp_path)

        path = create_entry("TestMac", "/usr/local/bin/test-mac", comment="Mac app")

        assert path == tmp_path / "TestMac.app"
        assert (path / "Contents" / "Info.plist").exists()
        assert (path / "Contents" / "MacOS" / "launcher").exists()
        assert (path / "Contents" / "Resources").is_dir()

        # Launcher is executable and has correct content
        launcher = path / "Contents" / "MacOS" / "launcher"
        assert launcher.stat().st_mode & 0o111  # executable bits
        content = launcher.read_text()
        assert "#!/bin/bash" in content
        assert "exec /usr/local/bin/test-mac" in content

        # Info.plist has correct bundle ID
        plist = (path / "Contents" / "Info.plist").read_text()
        assert "com.wesktop.testmac" in plist
        assert "<string>TestMac</string>" in plist

    def test_create_with_icon(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify icon is copied into Resources."""
        monkeypatch.setattr("wesktop.entries._macos_apps_dir", lambda: tmp_path)

        icon_src = tmp_path / "app.icns"
        icon_src.write_bytes(b"icns data")

        path = create_entry("IconMac", "/usr/bin/icon-mac", icon=icon_src)
        assert (path / "Contents" / "Resources" / "icon.icns").exists()

    def test_remove(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("wesktop.entries._macos_apps_dir", lambda: tmp_path)
        create_entry("RmMac", "/usr/bin/rm-mac")
        assert remove_entry("RmMac") is True
        assert not (tmp_path / "RmMac.app").exists()


# ---------------------------------------------------------------------------
# Windows tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestWindows:
    def test_create_shortcut(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify .lnk file creation (requires pywin32 or PowerShell)."""
        monkeypatch.setattr("wesktop.entries._windows_start_menu_dir", lambda: tmp_path)

        path = create_entry("TestWin", "C:\\Program Files\\test.exe --arg")
        assert path == tmp_path / "TestWin.lnk"
        assert path.exists()

    def test_remove(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("wesktop.entries._windows_start_menu_dir", lambda: tmp_path)
        create_entry("RmWin", "C:\\test.exe")
        assert remove_entry("RmWin") is True
        assert not (tmp_path / "RmWin.lnk").exists()


# ---------------------------------------------------------------------------
# Cross-platform tests
# ---------------------------------------------------------------------------

def test_unsupported_platform() -> None:
    """Unsupported platform raises OSError."""
    with patch("wesktop.entries.platform.system", return_value="FreeBSD"):
        with pytest.raises(OSError, match="Unsupported platform: FreeBSD"):
            create_entry("Test", "/bin/test")


def test_remove_unsupported_platform() -> None:
    """Remove on unsupported platform returns False."""
    with patch("wesktop.entries.platform.system", return_value="FreeBSD"):
        assert remove_entry("Test") is False
