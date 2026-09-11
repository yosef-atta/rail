"""Unit tests for Rail static validation engine."""

import copy
from pathlib import Path
import pytest

from rail.cli import cmd_validate
from rail.core.exceptions import RailValidationError
from rail.core.loader import load_raw_workflow
from rail.core.validator import validate_workflow


@pytest.fixture
def valid_default_data(default_workflow_path: Path) -> dict:
    return load_raw_workflow(default_workflow_path)


@pytest.fixture
def valid_careful_data(careful_feature_workflow_path: Path) -> dict:
    return load_raw_workflow(careful_feature_workflow_path)


def test_valid_default_workflow(valid_default_data: dict):
    result = validate_workflow(valid_default_data)
    assert result.is_valid is True
    assert len(result.errors) == 0


def test_valid_careful_feature_workflow(valid_careful_data: dict):
    result = validate_workflow(valid_careful_data)
    assert result.is_valid is True
    assert len(result.errors) == 0


def test_valid_fast_fix_workflow(fast_fix_workflow_path: Path):
    data = load_raw_workflow(fast_fix_workflow_path)
    result = validate_workflow(data)
    assert result.is_valid is True
    assert len(result.errors) == 0


# Root-level field validation tests
def test_missing_version(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["version"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_version" for e in result.errors)


def test_unsupported_version(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["version"] = "2.0"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "unsupported_version" for e in result.errors)


def test_missing_name(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["name"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_name" for e in result.errors)


def test_missing_start(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["start"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_start" for e in result.errors)


def test_missing_steps(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_steps" for e in result.errors)


def test_empty_steps(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"] = {}
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "empty_steps" for e in result.errors)


def test_invalid_start_target(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["start"] = "nonexistent_step"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_start_target" for e in result.errors)


# Referencing integrity tests
def test_dangling_next_target(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["next"] = "ghost_step"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "dangling_next_target" and e.step_id == "plan" for e in result.errors)


def test_dangling_transition_target(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["transitions"]["approved"] = "missing_target"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "dangling_transition_target" and e.step_id == "review_plan" for e in result.errors)


def test_unreachable_step(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["orphaned_step"] = {
        "type": "agent",
        "role": "main",
        "prompt": "I am alone",
        "next": "done",
    }
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "unreachable_step" and e.step_id == "orphaned_step" for e in result.errors)


def test_no_reachable_end_step(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    # Loop human_review back to implement instead of done, making done unreachable
    data["steps"]["human_review"]["transitions"]["approve"] = "implement"
    del data["steps"]["done"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "no_reachable_end_step" for e in result.errors)


# Mutual exclusivity
def test_step_both_next_and_transitions(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["transitions"] = {"ok": "implement"}
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "mutual_exclusion_violation" and e.step_id == "plan" for e in result.errors)


# Agent step rules
def test_agent_missing_role(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["plan"]["role"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_role" and e.step_id == "plan" for e in result.errors)


def test_agent_invalid_role(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["role"] = "superagent"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_role" and e.step_id == "plan" for e in result.errors)


def test_agent_missing_prompt(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["plan"]["prompt"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_prompt" and e.step_id == "plan" for e in result.errors)


def test_agent_empty_prompt(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["prompt"] = "   \n\t  "
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "empty_prompt" and e.step_id == "plan" for e in result.errors)


def test_subagent_missing_name(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["review_plan"]["name"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_subagent_name" and e.step_id == "review_plan" for e in result.errors)


# Choice / Result rules
def test_choice_missing_transitions(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["review_plan"]["transitions"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_choice_transitions" and e.step_id == "review_plan" for e in result.errors)


def test_choice_transition_mismatch_missing_option_transition(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["review_plan"]["transitions"]["changes_required"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "choice_transition_mismatch" and e.step_id == "review_plan" for e in result.errors)


def test_choice_transition_mismatch_extra_transition(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["transitions"]["maybe"] = "plan"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "choice_transition_mismatch" and e.step_id == "review_plan" for e in result.errors)


def test_choice_with_next(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    # Give review_plan both choice result and next (also triggers mutual exclusion)
    data["steps"]["review_plan"]["next"] = "implement"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "choice_with_next" for e in result.errors)


def test_agent_without_result_missing_next(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["plan"]["next"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_next" and e.step_id == "plan" for e in result.errors)


# Human step rules
def test_human_missing_message(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["human_review"]["message"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_message" and e.step_id == "human_review" for e in result.errors)


def test_human_missing_transitions(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["human_review"]["transitions"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_human_transitions" and e.step_id == "human_review" for e in result.errors)


def test_human_declaring_next(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["human_review"]["transitions"]
    data["steps"]["human_review"]["next"] = "done"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "human_with_next" and e.step_id == "human_review" for e in result.errors)


# End step rules
def test_end_declaring_next(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["done"]["next"] = "plan"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "end_with_next" and e.step_id == "done" for e in result.errors)


def test_end_declaring_transitions(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["done"]["transitions"] = {"restart": "plan"}
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "end_with_transitions" and e.step_id == "done" for e in result.errors)


# Excluded features and step types
def test_excluded_step_type_command(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["type"] = "command"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_step_type" for e in result.errors)


def test_excluded_step_type_action(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["type"] = "action"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_step_type" for e in result.errors)


def test_excluded_step_type_workflow(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["type"] = "workflow"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_step_type" for e in result.errors)


def test_excluded_root_feature_parallel(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["parallel"] = ["plan", "implement"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_feature" and e.field == "parallel" for e in result.errors)


def test_excluded_step_feature_retry(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["retry"] = {"max": 3}
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_feature" and e.field == "retry" for e in result.errors)


def test_excluded_variables_interpolation(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["prompt"] = "Execute task ${task} in repo ${repo}"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_feature" and "${task}" in e.message for e in result.errors)


def test_excluded_when_expression(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["when"] = "output.score > 80"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_feature" and "when" in e.message for e in result.errors)


def test_raise_on_error():
    broken_data = {"version": "0.1"}
    with pytest.raises(RailValidationError) as exc_info:
        validate_workflow(broken_data, raise_on_error=True)
    assert "Static validation failed" in str(exc_info.value)


def test_validator_non_dict_raw_data():
    result = validate_workflow("not-a-dict")
    assert result.is_valid is False
    assert any(e.rule == "invalid_schema" for e in result.errors)


def test_validator_step_not_a_dict(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"] = "not-a-dict-step"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_step_schema" for e in result.errors)


def test_validator_step_missing_type(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    del data["steps"]["plan"]["type"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_step_type" for e in result.errors)


def test_validator_step_invalid_type(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["type"] = "quantum_step"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_step_type" for e in result.errors)


def test_human_step_forbidden_properties(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["human_review"]["role"] = "main"
    data["steps"]["human_review"]["prompt"] = "Should not have prompt"
    data["steps"]["human_review"]["result"] = {"type": "choice"}
    result = validate_workflow(data)
    assert result.is_valid is False
    forbidden_fields = {e.field for e in result.errors if e.rule == "forbidden_property"}
    assert "role" in forbidden_fields
    assert "prompt" in forbidden_fields
    assert "result" in forbidden_fields


def test_end_step_forbidden_properties(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["done"]["message"] = "Should not have message"
    data["steps"]["done"]["prompt"] = "Should not have prompt"
    data["steps"]["done"]["role"] = "main"
    data["steps"]["done"]["name"] = "final"
    result = validate_workflow(data)
    assert result.is_valid is False
    forbidden_fields = {e.field for e in result.errors if e.rule == "forbidden_property"}
    assert "message" in forbidden_fields
    assert "prompt" in forbidden_fields
    assert "role" in forbidden_fields
    assert "name" in forbidden_fields


def test_invalid_next_target_empty_string(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["next"] = "   "
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_next_target" for e in result.errors)


def test_invalid_transition_target_empty_string(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["transitions"]["approved"] = ""
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_transition_target" for e in result.errors)


def test_invalid_transitions_not_a_dict(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["transitions"] = "not-a-dict"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_transitions" for e in result.errors)


def test_validate_workflow_instance_direct(valid_default_data: dict):
    from rail.core.models import Workflow
    wf = Workflow.model_validate(valid_default_data)
    result = validate_workflow(wf)
    assert result.is_valid is True


def test_nested_list_variable_interpolation(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["plan"]["extra_list"] = ["clean", "interpolated_${task}"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "excluded_feature" and "${task}" in e.message for e in result.errors)


def test_steps_not_a_dict(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"] = ["step1", "step2"]
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_steps" for e in result.errors)


def test_result_not_a_dict(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["result"] = "just_a_string"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "invalid_result_schema" for e in result.errors)


def test_result_unsupported_type(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["result"]["type"] = "json_schema"
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "unsupported_result_type" for e in result.errors)


def test_result_empty_options(valid_default_data: dict):
    data = copy.deepcopy(valid_default_data)
    data["steps"]["review_plan"]["result"]["options"] = []
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(e.rule == "missing_choice_options" for e in result.errors)


def test_validation_issue_str_formatting():
    from rail.core.exceptions import ValidationErrorIssue
    issue_with_field_only = ValidationErrorIssue(rule="missing_field", message="Field missing", field="my_field")
    assert str(issue_with_field_only) == "[missing_field] (field 'my_field'): Field missing"


def test_cli_cmd_validate(default_workflow_path: Path, tmp_path: Path):
    # Valid workflow returns 0
    assert cmd_validate(str(default_workflow_path)) == 0

    # Invalid workflow file returns 1
    invalid_file = tmp_path / "invalid.yaml"
    invalid_file.write_text("version: '0.1'\nname: bad\nstart: missing\nsteps: {}\n", encoding="utf-8")
    assert cmd_validate(str(invalid_file)) == 1

    # Non-existent workflow returns 1
    assert cmd_validate("non_existent_wf_12345") == 1
