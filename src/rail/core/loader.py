"""Filesystem loader for discovering and parsing workflow definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from rail.core.exceptions import RailWorkflowNotFoundError, RailWorkflowParseError
from rail.core.models import Workflow
from rail.core.validator import validate_workflow


def get_default_workflows_dir() -> Path:
    """Return the global workflows directory: ~/.rail/workflows/."""
    return Path.home() / ".rail" / "workflows"


def find_workflow_file(
    workflow_name_or_path: Union[str, Path],
    workflows_dir: Optional[Path] = None,
) -> Path:
    """Locate a workflow file by name or path.

    Searches for exact path first, then looks in workflows_dir for
    <name>.yaml or <name>.yml.
    """
    candidate_path = Path(workflow_name_or_path)

    # 1. Direct path check (if user passed a path with .yaml/.yml or existing file)
    if candidate_path.is_file():
        return candidate_path.resolve()

    # If it's a relative path in cwd with extension that exists
    if candidate_path.suffix in {".yaml", ".yml"} and candidate_path.exists():
        return candidate_path.resolve()

    # 2. Search in workflows_dir (or default ~/.rail/workflows/)
    target_dir = Path(workflows_dir).resolve() if workflows_dir else get_default_workflows_dir()
    searched: List[str] = [str(candidate_path.resolve()) if candidate_path.is_absolute() else str(candidate_path)]

    name = candidate_path.name
    # Strip extension if passed
    if name.endswith(".yaml") or name.endswith(".yml"):
        base_name = name.rsplit(".", 1)[0]
    else:
        base_name = name

    for ext in [".yaml", ".yml"]:
        p = target_dir / f"{base_name}{ext}"
        searched.append(str(p))
        if p.is_file():
            return p.resolve()

    raise RailWorkflowNotFoundError(str(workflow_name_or_path), searched_paths=searched)


def load_raw_workflow(file_path: Union[str, Path]) -> Dict[str, Any]:
    """Parse raw YAML mapping from a workflow file."""
    path = Path(file_path)
    if not path.is_file():
        raise RailWorkflowNotFoundError(str(file_path), searched_paths=[str(path.resolve())])

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RailWorkflowParseError(f"Cannot read file: {exc}", file_path=str(path)) from exc

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise RailWorkflowParseError(str(exc), file_path=str(path)) from exc

    if not isinstance(parsed, dict):
        raise RailWorkflowParseError(
            f"Expected a YAML mapping, got {type(parsed).__name__}",
            file_path=str(path),
        )

    return parsed


def load_workflow_from_file(file_path: Union[str, Path], validate: bool = True) -> Workflow:
    """Load and optionally statically validate a workflow from a file path."""
    raw_data = load_raw_workflow(file_path)

    if validate:
        validate_workflow(raw_data, raise_on_error=True)

    return Workflow.model_validate(raw_data)


def load_workflow(
    workflow_name_or_path: Union[str, Path],
    workflows_dir: Optional[Path] = None,
    validate: bool = True,
) -> Workflow:
    """Locate, load, and validate a workflow by name or file path."""
    file_path = find_workflow_file(workflow_name_or_path, workflows_dir=workflows_dir)
    return load_workflow_from_file(file_path, validate=validate)


def list_workflow_files(workflows_dir: Optional[Path] = None) -> List[Path]:
    """Discover all .yaml and .yml workflow files in workflows_dir."""
    target_dir = Path(workflows_dir).resolve() if workflows_dir else get_default_workflows_dir()
    if not target_dir.is_dir():
        return []

    found: List[Path] = []
    for ext in ["*.yaml", "*.yml"]:
        found.extend(target_dir.glob(ext))

    return sorted(found)
