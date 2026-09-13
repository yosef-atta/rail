"""Static validation engine for Workflow Language v0.1."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from rail.core.exceptions import RailValidationError, ValidationErrorIssue, ValidationResult
from rail.core.models import EndStatus, Role, Workflow

SUPPORTED_VERSIONS = {"0.1"}
SUPPORTED_STEP_TYPES = {"agent", "human", "end"}
EXCLUDED_STEP_TYPES = {"command", "action", "workflow"}
EXCLUDED_ROOT_KEYS = {
    "parallel",
    "retry",
    "timeout",
    "variables",
    "context",
    "tools",
    "agents",
    "prompts",
    "when",
}
EXCLUDED_STEP_KEYS = {
    "parallel",
    "retry",
    "timeout",
    "run",
    "action",
    "use",
    "when",
    "system_prompt",
    "prepend_prompt",
    "append_prompt",
}

VAR_EXPR_PATTERN = re.compile(r"(\$\{[^}]+\}|\{\{[^}]+\}\})")


class StaticValidator:
    """Validate workflow definitions against Workflow Language v0.1."""

    def __init__(self, raw_data: Optional[Dict[str, Any]] = None, workflow: Optional[Workflow] = None) -> None:
        self.raw_data = raw_data or (workflow.model_dump() if workflow else {})
        self.workflow = workflow
        self.errors: List[ValidationErrorIssue] = []
        self.warnings: List[ValidationErrorIssue] = []

    def add_error(self, rule: str, message: str, step_id: Optional[str] = None, field: Optional[str] = None) -> None:
        self.errors.append(ValidationErrorIssue(rule=rule, message=message, step_id=step_id, field=field))

    def validate(self) -> ValidationResult:
        self.errors.clear()
        self.warnings.clear()

        if not isinstance(self.raw_data, dict):
            self.add_error("invalid_schema", "Workflow definition must be a YAML mapping/dictionary.")
            return ValidationResult(is_valid=False, errors=self.errors, warnings=self.warnings)

        for key in self.raw_data:
            if key in EXCLUDED_ROOT_KEYS:
                self.add_error("excluded_feature", f"'{key}' is not supported in Workflow Language v0.1.", field=key)

        self._validate_root_fields()
        self._check_for_variables_and_expressions(self.raw_data)

        steps_data = self.raw_data.get("steps")
        if not isinstance(steps_data, dict) or not steps_data:
            if "steps" in self.raw_data and not any(error.field == "steps" for error in self.errors):
                self.add_error("empty_steps", "'steps' must be a non-empty mapping.", field="steps")
            return ValidationResult(is_valid=False, errors=self.errors, warnings=self.warnings)

        start_step = self.raw_data.get("start")
        if isinstance(start_step, str) and start_step not in steps_data:
            self.add_error("invalid_start_target", f"Start step '{start_step}' does not exist in 'steps'.", field="start")

        for step_id, step in steps_data.items():
            self._validate_step(step_id, step, steps_data)

        if not any(error.rule in {"invalid_step_type", "invalid_schema"} for error in self.errors):
            self._validate_graph(start_step, steps_data)

        return ValidationResult(is_valid=not self.errors, errors=self.errors, warnings=self.warnings)

    def _validate_root_fields(self) -> None:
        version = self.raw_data.get("version")
        if version is None:
            self.add_error("missing_version", "'version' is required.", field="version")
        elif str(version) not in SUPPORTED_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_VERSIONS))
            self.add_error("unsupported_version", f"Unsupported version '{version}'. Supported versions: {supported}.", field="version")

        name = self.raw_data.get("name")
        if not isinstance(name, str) or not name.strip():
            self.add_error("missing_name", "'name' is required and must be a non-empty string.", field="name")

        start = self.raw_data.get("start")
        if not isinstance(start, str) or not start.strip():
            self.add_error("missing_start", "'start' is required and must be a non-empty string.", field="start")

        steps = self.raw_data.get("steps")
        if steps is None:
            self.add_error("missing_steps", "'steps' mapping is required.", field="steps")
        elif not isinstance(steps, dict):
            self.add_error("invalid_steps", "'steps' must be a mapping.", field="steps")

    def _validate_step(self, step_id: str, step: Any, all_steps: Dict[str, Any]) -> None:
        if not isinstance(step, dict):
            self.add_error("invalid_step_schema", f"Step '{step_id}' must be a mapping.", step_id=step_id)
            return

        for key in step:
            if key in EXCLUDED_STEP_KEYS:
                self.add_error(
                    "excluded_feature",
                    f"Property '{key}' in step '{step_id}' is not supported in Workflow Language v0.1.",
                    step_id=step_id,
                    field=key,
                )

        step_type = step.get("type")
        if not step_type:
            self.add_error("missing_step_type", f"Step '{step_id}' is missing required 'type'.", step_id=step_id, field="type")
            return
        if step_type in EXCLUDED_STEP_TYPES:
            self.add_error("excluded_step_type", f"Step '{step_id}' uses excluded step type '{step_type}'.", step_id=step_id, field="type")
            return
        if step_type not in SUPPORTED_STEP_TYPES:
            supported = ", ".join(sorted(SUPPORTED_STEP_TYPES))
            self.add_error("invalid_step_type", f"Step '{step_id}' has unsupported type '{step_type}'. Supported types: {supported}.", step_id=step_id, field="type")
            return

        has_next = "next" in step and step["next"] is not None
        has_transitions = "transitions" in step and step["transitions"] is not None

        if has_next and has_transitions:
            self.add_error("mutual_exclusion_violation", f"Step '{step_id}' cannot declare both 'next' and 'transitions'.", step_id=step_id)

        if has_next:
            next_target = step["next"]
            if not isinstance(next_target, str) or not next_target.strip():
                self.add_error("invalid_next_target", f"Step '{step_id}' has an invalid 'next' target.", step_id=step_id, field="next")
            elif next_target not in all_steps:
                self.add_error("dangling_next_target", f"Step '{step_id}' specifies 'next: {next_target}', which does not exist in 'steps'.", step_id=step_id, field="next")

        if has_transitions:
            transitions = step["transitions"]
            if not isinstance(transitions, dict) or not transitions:
                self.add_error("invalid_transitions", f"Step '{step_id}' 'transitions' must be a non-empty mapping.", step_id=step_id, field="transitions")
            else:
                for action, target in transitions.items():
                    if not isinstance(target, str) or not target.strip():
                        self.add_error("invalid_transition_target", f"Step '{step_id}' transition '{action}' has invalid target '{target}'.", step_id=step_id, field="transitions")
                    elif target not in all_steps:
                        self.add_error("dangling_transition_target", f"Step '{step_id}' transition '{action}' points to non-existent step '{target}'.", step_id=step_id, field="transitions")

        if step_type == "agent":
            self._validate_agent_step(step_id, step, has_next, has_transitions)
        elif step_type == "human":
            self._validate_human_step(step_id, step, has_next, has_transitions)
        else:
            self._validate_end_step(step_id, step, has_next, has_transitions)

    def _validate_agent_step(self, step_id: str, step: Dict[str, Any], has_next: bool, has_transitions: bool) -> None:
        role = step.get("role")
        if role is None:
            self.add_error("missing_role", f"Agent step '{step_id}' requires 'role'.", step_id=step_id, field="role")
        elif role not in {role.value for role in Role}:
            self.add_error("invalid_role", f"Agent step '{step_id}' has invalid role '{role}'. Allowed roles: main, subagent.", step_id=step_id, field="role")
        elif role == Role.SUBAGENT.value:
            name = step.get("name")
            if not isinstance(name, str) or not name.strip():
                self.add_error("missing_subagent_name", f"Subagent step '{step_id}' requires a non-empty 'name'.", step_id=step_id, field="name")

        prompt = step.get("prompt")
        if prompt is None:
            self.add_error("missing_prompt", f"Agent step '{step_id}' requires 'prompt'.", step_id=step_id, field="prompt")
        elif not isinstance(prompt, str) or not prompt.strip():
            self.add_error("empty_prompt", f"Agent step '{step_id}' 'prompt' cannot be empty or whitespace only.", step_id=step_id, field="prompt")

        result = step.get("result")
        if result is not None:
            if not isinstance(result, dict):
                self.add_error("invalid_result_schema", f"Agent step '{step_id}' 'result' must be a mapping.", step_id=step_id, field="result")
                return

            result_type = result.get("type")
            if result_type != "choice":
                self.add_error("unsupported_result_type", f"Agent step '{step_id}' result type '{result_type}' is unsupported. Only 'choice' is allowed.", step_id=step_id, field="result.type")

            options = result.get("options")
            if not isinstance(options, list) or not options:
                self.add_error("missing_choice_options", f"Agent step '{step_id}' choice result requires a non-empty 'options' list.", step_id=step_id, field="result.options")
            else:
                transitions = step.get("transitions")
                if not isinstance(transitions, dict):
                    self.add_error("missing_choice_transitions", f"Agent step '{step_id}' has choice result but is missing 'transitions'.", step_id=step_id, field="transitions")
                else:
                    option_set = {str(option) for option in options}
                    transition_set = set(transitions)
                    missing = option_set - transition_set
                    extra = transition_set - option_set
                    if missing:
                        self.add_error("choice_transition_mismatch", f"Agent step '{step_id}' options {sorted(missing)} do not have corresponding transitions.", step_id=step_id, field="transitions")
                    if extra:
                        self.add_error("choice_transition_mismatch", f"Agent step '{step_id}' transitions {sorted(extra)} are not defined in result options.", step_id=step_id, field="transitions")

            if has_next:
                self.add_error("choice_with_next", f"Agent step '{step_id}' with choice result cannot declare 'next'.", step_id=step_id, field="next")
        elif not has_next:
            self.add_error("missing_next", f"Agent step '{step_id}' without result must declare 'next'.", step_id=step_id, field="next")

    def _validate_human_step(self, step_id: str, step: Dict[str, Any], has_next: bool, has_transitions: bool) -> None:
        message = step.get("message")
        if not isinstance(message, str) or not message.strip():
            self.add_error("missing_message", f"Human gate step '{step_id}' requires a non-empty 'message'.", step_id=step_id, field="message")
        if not has_transitions:
            self.add_error("missing_human_transitions", f"Human gate step '{step_id}' requires 'transitions'.", step_id=step_id, field="transitions")
        if has_next:
            self.add_error("human_with_next", f"Human gate step '{step_id}' cannot declare 'next'. Use 'transitions'.", step_id=step_id, field="next")
        for forbidden in ("role", "prompt", "result"):
            if forbidden in step and step[forbidden] is not None:
                self.add_error("forbidden_property", f"Human step '{step_id}' cannot declare '{forbidden}'.", step_id=step_id, field=forbidden)

    def _validate_end_step(self, step_id: str, step: Dict[str, Any], has_next: bool, has_transitions: bool) -> None:
        if has_next:
            self.add_error("end_with_next", f"End step '{step_id}' cannot declare 'next'.", step_id=step_id, field="next")
        if has_transitions:
            self.add_error("end_with_transitions", f"End step '{step_id}' cannot declare 'transitions'.", step_id=step_id, field="transitions")

        status = step.get("status", EndStatus.COMPLETED.value)
        allowed_statuses = {status.value for status in EndStatus}
        if status not in allowed_statuses:
            allowed = ", ".join(sorted(allowed_statuses))
            self.add_error("invalid_end_status", f"End step '{step_id}' has invalid status '{status}'. Allowed statuses: {allowed}.", step_id=step_id, field="status")

        for forbidden in ("prompt", "message", "role", "result", "name"):
            if forbidden in step and step[forbidden] is not None:
                self.add_error("forbidden_property", f"End step '{step_id}' cannot declare '{forbidden}'.", step_id=step_id, field=forbidden)

    def _validate_graph(self, start_step: Optional[str], all_steps: Dict[str, Any]) -> None:
        if not start_step or start_step not in all_steps:
            return

        visited: Set[str] = set()
        queue = [start_step]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            step = all_steps.get(current)
            if not isinstance(step, dict):
                continue

            next_step = step.get("next")
            if isinstance(next_step, str) and next_step in all_steps and next_step not in visited:
                queue.append(next_step)

            transitions = step.get("transitions")
            if isinstance(transitions, dict):
                for target in transitions.values():
                    if isinstance(target, str) and target in all_steps and target not in visited:
                        queue.append(target)

        for unreachable in sorted(set(all_steps) - visited):
            self.add_error("unreachable_step", f"Step '{unreachable}' is unreachable from start step '{start_step}'.", step_id=unreachable)

        reachable_end_steps = [
            step_id
            for step_id in visited
            if isinstance(all_steps.get(step_id), dict) and all_steps[step_id].get("type") == "end"
        ]
        if not reachable_end_steps:
            self.add_error("no_reachable_end_step", "Workflow has no reachable 'end' step from start.")

    def _check_for_variables_and_expressions(self, data: Any, current_path: str = "") -> None:
        if isinstance(data, str):
            match = VAR_EXPR_PATTERN.search(data)
            if match:
                self.add_error("excluded_feature", f"Variables/expressions like '{match.group(1)}' are not supported in Workflow Language v0.1.", field=current_path or None)
        elif isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{current_path}.{key}" if current_path else key
                if key == "when":
                    self.add_error("excluded_feature", "Conditional expression 'when' is not supported in Workflow Language v0.1.", field=new_path)
                self._check_for_variables_and_expressions(value, new_path)
        elif isinstance(data, list):
            for index, item in enumerate(data):
                self._check_for_variables_and_expressions(item, f"{current_path}[{index}]")


def validate_workflow(
    workflow_or_data: Workflow | Dict[str, Any],
    raw_data: Optional[Dict[str, Any]] = None,
    raise_on_error: bool = False,
) -> ValidationResult:
    """Validate a workflow against Workflow Language v0.1 rules."""
    if isinstance(workflow_or_data, Workflow):
        data = raw_data or workflow_or_data.model_dump(mode="json")
        validator = StaticValidator(raw_data=data, workflow=workflow_or_data)
    else:
        validator = StaticValidator(raw_data=workflow_or_data)

    result = validator.validate()
    if raise_on_error and result.has_errors:
        raise RailValidationError(
            f"Static validation failed with {len(result.errors)} error(s):",
            errors=result.errors,
        )
    return result
