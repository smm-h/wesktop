"""Tests for the `python -m wesktop` entry point (__main__.py)."""

import subprocess
import sys


def test_import_main_does_not_invoke_cli():
    """Importing wesktop.__main__ must not run the CLI (no __name__ guard bug)."""
    result = subprocess.run(
        [sys.executable, "-c", "import wesktop.__main__"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # The CLI prints a help banner when run with no args; importing must not.
    assert result.stdout == "", f"import invoked the CLI: {result.stdout!r}"


def test_run_module_invokes_cli():
    """`python -m wesktop diagnose` must run the CLI via the guarded main()."""
    result = subprocess.run(
        [sys.executable, "-m", "wesktop", "diagnose"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Python" in result.stdout
