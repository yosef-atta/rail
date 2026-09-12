"""Unit tests for Rail CLI."""

from pathlib import Path
from rail.cli import main


def test_cli_main_valid(default_workflow_path: Path):
    exit_code = main(["validate", str(default_workflow_path)])
    assert exit_code == 0


def test_cli_main_invalid_file(tmp_path: Path):
    invalid_wf = tmp_path / "broken.yaml"
    invalid_wf.write_text("version: '0.1'\nname: bad\nstart: s\nsteps: {}\n", encoding="utf-8")
    exit_code = main(["validate", str(invalid_wf)])
    assert exit_code == 1


def test_cli_main_not_found():
    exit_code = main(["validate", "nonexistent_workflow_name"])
    assert exit_code == 1


def test_cli_main_syntax_error(tmp_path: Path):
    broken_yaml = tmp_path / "syntax_err.yaml"
    broken_yaml.write_text("version: [broken yaml", encoding="utf-8")
    exit_code = main(["validate", str(broken_yaml)])
    assert exit_code == 1


def test_cli_main_no_args():
    exit_code = main([])
    assert exit_code == 0


def test_cli_serve_exit(monkeypatch):
    """Verify serve command handles KeyboardInterrupt cleanly."""
    def mock_run_mcp_server(**kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("rail.mcp.server.run_mcp_server", mock_run_mcp_server)
    exit_code = main(["serve"])
    assert exit_code == 0

