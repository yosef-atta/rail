"""Unit tests for Rail filesystem loader."""

from pathlib import Path
import pytest

from rail.core.exceptions import RailWorkflowNotFoundError, RailWorkflowParseError
from rail.core.loader import (
    find_workflow_file,
    get_default_workflows_dir,
    list_workflow_files,
    load_raw_workflow,
    load_workflow,
    load_workflow_from_file,
)
from rail.core.models import AgentStep, EndStep, HumanStep, Workflow


def test_get_default_workflows_dir():
    expected = Path.home() / ".rail" / "workflows"
    assert get_default_workflows_dir() == expected


def test_load_workflow_from_file_valid_default(default_workflow_path: Path):
    wf = load_workflow_from_file(default_workflow_path)
    assert isinstance(wf, Workflow)
    assert wf.name == "default"
    assert wf.version == "0.1"
    assert wf.start == "plan"
    assert "plan" in wf.steps
    assert isinstance(wf.steps["plan"], AgentStep)
    assert isinstance(wf.steps["human_review"], HumanStep)
    assert isinstance(wf.steps["done"], EndStep)


def test_load_workflow_from_file_valid_careful_feature(careful_feature_workflow_path: Path):
    wf = load_workflow_from_file(careful_feature_workflow_path)
    assert wf.name == "careful-feature"
    assert wf.steps["review_plan"].role.value == "subagent"
    assert wf.steps["review_plan"].name == "plan-reviewer"


def test_load_workflow_from_file_valid_fast_fix_yml(fast_fix_workflow_path: Path):
    wf = load_workflow_from_file(fast_fix_workflow_path)
    assert wf.name == "fast-fix"
    assert wf.start == "fix"


def test_find_workflow_file_direct_path(default_workflow_path: Path):
    found = find_workflow_file(default_workflow_path)
    assert found == default_workflow_path.resolve()


def test_find_workflow_file_in_directory(temp_workflows_dir: Path):
    sample_file = temp_workflows_dir / "my-workflow.yaml"
    sample_file.write_text("version: '0.1'\nname: my-workflow\nstart: s\nsteps: {}\n", encoding="utf-8")

    found = find_workflow_file("my-workflow", workflows_dir=temp_workflows_dir)
    assert found == sample_file.resolve()

    # Also test passing with extension
    found_ext = find_workflow_file("my-workflow.yaml", workflows_dir=temp_workflows_dir)
    assert found_ext == sample_file.resolve()


def test_find_workflow_file_yml_extension(temp_workflows_dir: Path):
    sample_file = temp_workflows_dir / "quick-fix.yml"
    sample_file.write_text("version: '0.1'\nname: quick-fix\nstart: s\nsteps: {}\n", encoding="utf-8")

    found = find_workflow_file("quick-fix", workflows_dir=temp_workflows_dir)
    assert found == sample_file.resolve()


def test_find_workflow_file_not_found(temp_workflows_dir: Path):
    with pytest.raises(RailWorkflowNotFoundError) as exc_info:
        find_workflow_file("nonexistent", workflows_dir=temp_workflows_dir)
    assert "nonexistent" in str(exc_info.value)


def test_load_workflow_by_name(temp_workflows_dir: Path, default_workflow_path: Path):
    # Copy default.yaml into temp_workflows_dir
    target = temp_workflows_dir / "default.yaml"
    target.write_text(default_workflow_path.read_text(encoding="utf-8"), encoding="utf-8")

    wf = load_workflow("default", workflows_dir=temp_workflows_dir)
    assert wf.name == "default"


def test_load_raw_workflow_malformed_yaml(tmp_path: Path):
    broken_yaml = tmp_path / "broken.yaml"
    broken_yaml.write_text("version: 0.1\n  steps: [invalid yaml mapping", encoding="utf-8")

    with pytest.raises(RailWorkflowParseError) as exc_info:
        load_raw_workflow(broken_yaml)
    assert "Failed to parse workflow YAML" in str(exc_info.value)


def test_load_raw_workflow_not_a_mapping(tmp_path: Path):
    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text("- item 1\n- item 2\n", encoding="utf-8")

    with pytest.raises(RailWorkflowParseError) as exc_info:
        load_raw_workflow(list_yaml)
    assert "Expected a YAML mapping" in str(exc_info.value)


def test_list_workflow_files(temp_workflows_dir: Path):
    (temp_workflows_dir / "b.yaml").write_text("dummy", encoding="utf-8")
    (temp_workflows_dir / "a.yml").write_text("dummy", encoding="utf-8")
    (temp_workflows_dir / "ignored.txt").write_text("dummy", encoding="utf-8")

    files = list_workflow_files(temp_workflows_dir)
    assert len(files) == 2
    assert [f.name for f in files] == ["a.yml", "b.yaml"]
