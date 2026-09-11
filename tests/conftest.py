"""Pytest configuration and shared fixtures for Rail tests."""

from pathlib import Path
import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to tests/fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return path to tests/fixtures/valid directory."""
    return fixtures_dir / "valid"


@pytest.fixture
def default_workflow_path(valid_fixtures_dir: Path) -> Path:
    """Return path to valid default.yaml fixture."""
    return valid_fixtures_dir / "default.yaml"


@pytest.fixture
def careful_feature_workflow_path(valid_fixtures_dir: Path) -> Path:
    """Return path to valid careful-feature.yaml fixture."""
    return valid_fixtures_dir / "careful-feature.yaml"


@pytest.fixture
def fast_fix_workflow_path(valid_fixtures_dir: Path) -> Path:
    """Return path to valid fast-fix.yml fixture."""
    return valid_fixtures_dir / "fast-fix.yml"


@pytest.fixture
def temp_workflows_dir(tmp_path: Path) -> Path:
    """Create a temporary workflows directory mimicking ~/.rail/workflows/."""
    wf_dir = tmp_path / ".rail" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    return wf_dir
