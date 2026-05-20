"""Tests for the wesktop CLI."""

from wesktop.cli import app


def test_help():
    result = app.test([])
    assert result.exit_code == 0
    assert "wesktop" in result.stdout


def test_version():
    result = app.test(["--version"])
    assert result.exit_code == 0
    assert "wesktop" in result.stdout


def test_diagnose():
    result = app.test(["diagnose"])
    assert result.exit_code == 0
    assert "Python" in result.stdout
    assert "granian" in result.stdout
    assert "pywebview" in result.stdout
    assert "platform" in result.stdout


def test_config_path():
    result = app.test(["config", "path"])
    assert result.exit_code == 0
    assert "wesktop" in result.stdout
