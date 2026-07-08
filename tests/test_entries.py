from __future__ import annotations

import platform
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from wesktop.entries import (
    _split_windows_command,
    create_entry,
    create_launcher,
    entry_exists,
    launcher_path,
    quote_windows_command,
    remove_entry,
    remove_launcher,
)


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

    def test_exec_escapes_percent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Percent signs in the command are escaped as %% per the Desktop Entry spec."""
        apps_dir = tmp_path / "applications"
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: apps_dir)
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")

        path = create_entry("PctApp", "/usr/bin/pct-app --format %U-like")
        content = path.read_text()
        assert "Exec=/usr/bin/pct-app --format %%U-like" in content
        # No un-doubled percent remains in the Exec line
        exec_line = next(line for line in content.splitlines() if line.startswith("Exec="))
        assert exec_line.replace("%%", "").count("%") == 0

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
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")

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
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")

        result = remove_entry("DoesNotExist")
        assert result is False

    def test_entry_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """entry_exists reflects creation and removal."""
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: tmp_path / "applications")
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")

        assert entry_exists("ExistsApp") is False
        create_entry("ExistsApp", "/usr/bin/exists-app")
        assert entry_exists("ExistsApp") is True
        remove_entry("ExistsApp")
        assert entry_exists("ExistsApp") is False

    def test_remove_entry_removes_launcher(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """remove_entry also deletes the ~/.local/bin/<name>-open launcher script."""
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: tmp_path / "applications")
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")

        launcher = create_launcher("My App", "/usr/bin/my-app open")
        create_entry("My App", str(launcher))
        assert launcher.exists()

        assert remove_entry("My App") is True
        assert not launcher.exists()

    def test_remove_entry_returns_true_for_orphaned_launcher(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A leftover launcher with no desktop file still counts as removed."""
        monkeypatch.setattr("wesktop.entries._linux_apps_dir", lambda: tmp_path / "applications")
        monkeypatch.setattr("wesktop.entries._linux_icons_dir", lambda: tmp_path / "icons")
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")

        launcher = create_launcher("Orphan", "/usr/bin/orphan")
        assert remove_entry("Orphan") is True
        assert not launcher.exists()


# ---------------------------------------------------------------------------
# Launcher script tests (POSIX)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(platform.system() not in ("Linux", "Darwin"), reason="POSIX only")
class TestLauncher:
    def test_create_launcher(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Launcher script is created executable with the exact command."""
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")

        path = create_launcher("My App", "'/opt/My App/bin/my-app' open")
        assert path == tmp_path / "bin" / "my-app-open"
        assert path.read_text() == "#!/bin/sh\nexec '/opt/My App/bin/my-app' open\n"
        assert path.stat().st_mode & 0o111  # executable bits

    def test_launcher_path_naming(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """launcher_path derives the slugged '-open' name."""
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
        assert launcher_path("My Cool App") == tmp_path / "bin" / "my-cool-app-open"

    def test_remove_launcher(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
        create_launcher("Rm", "/usr/bin/rm-app")
        assert remove_launcher("Rm") is True
        assert remove_launcher("Rm") is False

    def test_create_launcher_rejected_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A POSIX shell script cannot execute on Windows -- hard error, never write it."""
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
        monkeypatch.setattr("wesktop.entries.platform.system", lambda: "Windows")

        with pytest.raises(OSError, match="Windows"):
            create_launcher("WinApp", "C:\\app.exe")
        assert not (tmp_path / "bin" / "winapp-open").exists()


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
        monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
        create_entry("RmMac", "/usr/bin/rm-mac")
        assert remove_entry("RmMac") is True
        assert not (tmp_path / "RmMac.app").exists()


# ---------------------------------------------------------------------------
# Windows command parsing (pure functions, run everywhere)
# ---------------------------------------------------------------------------

class TestSplitWindowsCommand:
    def test_quoted_target_with_spaces(self) -> None:
        target, args = _split_windows_command('"C:\\Program Files\\test.exe" --arg')
        assert target == "C:\\Program Files\\test.exe"
        assert args == "--arg"

    def test_quoted_target_no_arguments(self) -> None:
        target, args = _split_windows_command('"C:\\Program Files\\test.exe"')
        assert target == "C:\\Program Files\\test.exe"
        assert args == ""

    def test_unquoted_target_without_spaces(self) -> None:
        target, args = _split_windows_command("C:\\Tools\\app.exe --x --y")
        assert target == "C:\\Tools\\app.exe"
        assert args == "--x --y"

    def test_bare_command_with_arguments(self) -> None:
        target, args = _split_windows_command("python -m mypkg open")
        assert target == "python"
        assert args == "-m mypkg open"

    def test_unquoted_path_with_spaces_is_hard_error(self) -> None:
        """The pre-fix silent breakage case: never produce TargetPath='C:\\Program'."""
        with pytest.raises(ValueError, match="[Dd]ouble-quote"):
            _split_windows_command("C:\\Program Files\\test.exe --arg")

    def test_unterminated_quote_is_hard_error(self) -> None:
        with pytest.raises(ValueError, match="[Uu]nterminated"):
            _split_windows_command('"C:\\Program Files\\test.exe --arg')

    def test_empty_command_is_hard_error(self) -> None:
        with pytest.raises(ValueError):
            _split_windows_command("   ")


class TestQuoteWindowsCommand:
    def test_quotes_parts_with_spaces(self) -> None:
        line = quote_windows_command(["C:\\Program Files\\python.exe", "-m", "mypkg", "open"])
        assert line == '"C:\\Program Files\\python.exe" -m mypkg open'

    def test_no_quotes_when_not_needed(self) -> None:
        assert quote_windows_command(["C:\\Tools\\app.exe", "--x"]) == "C:\\Tools\\app.exe --x"

    def test_round_trips_through_split(self) -> None:
        line = quote_windows_command(["C:\\Program Files\\app.exe", "--flag", "value"])
        target, args = _split_windows_command(line)
        assert target == "C:\\Program Files\\app.exe"
        assert args == "--flag value"

    def test_embedded_double_quote_is_hard_error(self) -> None:
        with pytest.raises(ValueError, match="double quote"):
            quote_windows_command(['C:\\weird"name.exe'])


# ---------------------------------------------------------------------------
# Windows shortcut creation (cross-platform via monkeypatched COM/PowerShell)
# ---------------------------------------------------------------------------

class TestWindows:
    @pytest.fixture(autouse=True)
    def _windows_platform(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.start_menu = tmp_path / "StartMenu"
        monkeypatch.setattr("wesktop.entries.platform.system", lambda: "Windows")
        monkeypatch.setattr("wesktop.entries._windows_start_menu_dir", lambda: self.start_menu)

    def _install_fake_win32com(self, monkeypatch: pytest.MonkeyPatch) -> tuple[object, dict]:
        """Install a fake win32com.client module and return (shortcut, records)."""
        records: dict = {}

        class FakeShortcut:
            TargetPath = ""
            Arguments = ""
            Description = ""
            IconLocation = ""

            def save(self) -> None:
                records["saved"] = True

        shortcut = FakeShortcut()

        class FakeShell:
            def CreateShortCut(self, path: str) -> FakeShortcut:
                records["lnk_path"] = path
                return shortcut

        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = lambda progid: FakeShell()  # type: ignore[attr-defined]
        fake_pkg = types.ModuleType("win32com")
        fake_pkg.client = fake_client  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "win32com", fake_pkg)
        monkeypatch.setitem(sys.modules, "win32com.client", fake_client)
        return shortcut, records

    def test_com_backend_parses_quoted_path_with_spaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TargetPath/Arguments are split correctly for a Program Files path."""
        monkeypatch.setattr("wesktop.entries._windows_com_available", lambda: True)
        shortcut, records = self._install_fake_win32com(monkeypatch)

        path = create_entry("TestWin", '"C:\\Program Files\\test.exe" --arg')

        assert path == self.start_menu / "TestWin.lnk"
        assert records["lnk_path"] == str(self.start_menu / "TestWin.lnk")
        assert shortcut.TargetPath == "C:\\Program Files\\test.exe"
        assert shortcut.Arguments == "--arg"
        assert records["saved"] is True

    def test_powershell_backend_parses_quoted_path_with_spaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("wesktop.entries._windows_com_available", lambda: False)
        captured: dict = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("wesktop.entries.subprocess.run", fake_run)

        path = create_entry("PSWin", '"C:\\Program Files\\test.exe" --arg')

        assert path == self.start_menu / "PSWin.lnk"
        script = captured["cmd"][-1]
        assert "$s.TargetPath = 'C:\\Program Files\\test.exe';" in script
        assert "$s.Arguments = '--arg';" in script

    def test_com_failure_is_hard_error_without_powershell_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once the COM backend is selected, its failure propagates -- no silent retry."""
        monkeypatch.setattr("wesktop.entries._windows_com_available", lambda: True)

        def boom(progid: str) -> None:
            raise RuntimeError("COM exploded")

        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = boom  # type: ignore[attr-defined]
        fake_pkg = types.ModuleType("win32com")
        fake_pkg.client = fake_client  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "win32com", fake_pkg)
        monkeypatch.setitem(sys.modules, "win32com.client", fake_client)

        def no_powershell(*args, **kwargs):
            pytest.fail("PowerShell fallback must not run after COM was selected")

        monkeypatch.setattr("wesktop.entries.subprocess.run", no_powershell)

        with pytest.raises(RuntimeError, match="COM exploded"):
            create_entry("FailWin", "C:\\test.exe")

    def test_powershell_failure_is_hard_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PowerShell backend failures propagate as CalledProcessError."""
        monkeypatch.setattr("wesktop.entries._windows_com_available", lambda: False)

        def failing_run(cmd, *args, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, stderr=b"powershell broke")

        monkeypatch.setattr("wesktop.entries.subprocess.run", failing_run)

        with pytest.raises(subprocess.CalledProcessError):
            create_entry("FailPS", "C:\\test.exe")

    def test_unquoted_program_files_path_is_hard_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The old silent-breakage input now errors instead of a broken shortcut."""
        monkeypatch.setattr("wesktop.entries._windows_com_available", lambda: False)
        monkeypatch.setattr(
            "wesktop.entries.subprocess.run",
            lambda *a, **k: pytest.fail("shortcut must not be created for ambiguous command"),
        )

        with pytest.raises(ValueError, match="[Dd]ouble-quote"):
            create_entry("BadWin", "C:\\Program Files\\test.exe --arg")

    def test_backend_selection_prefers_com_when_pywin32_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_windows_com_available reflects pywin32 importability."""
        import importlib.util

        from wesktop.entries import _windows_com_available

        real_find_spec = importlib.util.find_spec

        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name, *a: object() if name == "win32com" else real_find_spec(name, *a),
        )
        assert _windows_com_available() is True

        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name, *a: None if name == "win32com" else real_find_spec(name, *a),
        )
        assert _windows_com_available() is False

    def test_remove(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.start_menu.mkdir(parents=True)
        lnk = self.start_menu / "RmWin.lnk"
        lnk.write_bytes(b"fake lnk")
        assert remove_entry("RmWin") is True
        assert not lnk.exists()

    def test_entry_exists_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert entry_exists("WinApp") is False
        self.start_menu.mkdir(parents=True)
        (self.start_menu / "WinApp.lnk").write_bytes(b"fake lnk")
        assert entry_exists("WinApp") is True


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


def test_create_launcher_unsupported_platform() -> None:
    """Launcher scripts hard-error on unsupported platforms."""
    with patch("wesktop.entries.platform.system", return_value="FreeBSD"):
        with pytest.raises(OSError, match="FreeBSD"):
            create_launcher("Test", "/bin/test")
