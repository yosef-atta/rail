"""Rail core exceptions and validation diagnostic models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationErrorIssue:
    """A single validation error or warning diagnostic."""

    rule: str
    message: str
    step_id: Optional[str] = None
    field: Optional[str] = None

    def __str__(self) -> str:
        prefix = f"[{self.rule}]"
        location = ""
        if self.step_id:
            location += f" (step '{self.step_id}'"
            if self.field:
                location += f", field '{self.field}'"
            location += ")"
        elif self.field:
            location += f" (field '{self.field}')"
        return f"{prefix}{location}: {self.message}"


@dataclass
class ValidationResult:
    """Result of static workflow validation."""

    is_valid: bool
    errors: list[ValidationErrorIssue] = field(default_factory=list)
    warnings: list[ValidationErrorIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


class RailError(Exception):
    """Base exception for all Rail errors."""


class RailWorkflowNotFoundError(RailError):
    """Raised when a requested workflow file cannot be located."""

    def __init__(self, workflow_name: str, searched_paths: list[str] | None = None) -> None:
        self.workflow_name = workflow_name
        self.searched_paths = searched_paths or []
        msg = f"Workflow '{workflow_name}' not found."
        if self.searched_paths:
            msg += f" Searched in: {', '.join(self.searched_paths)}"
        super().__init__(msg)


class RailWorkflowParseError(RailError):
    """Raised when a workflow file cannot be parsed as valid YAML."""

    def __init__(self, message: str, file_path: Optional[str] = None) -> None:
        self.file_path = file_path
        location = f" in {file_path}" if file_path else ""
        super().__init__(f"Failed to parse workflow YAML{location}: {message}")


class RailValidationError(RailError):
    """Raised when a workflow fails static validation."""

    def __init__(self, message: str, errors: list[ValidationErrorIssue] | None = None) -> None:
        self.errors = errors or []
        formatted_errors = "\n".join(f"  - {err}" for err in self.errors)
        full_msg = f"{message}\n{formatted_errors}" if formatted_errors else message
        super().__init__(full_msg)


class RailStorageError(RailError):
    """Base exception for storage and persistence errors."""


class RailRunNotFoundError(RailStorageError):
    """Raised when a requested run_id is not found in the state store."""

    def __init__(self, run_id: str, message: Optional[str] = None) -> None:
        self.run_id = run_id
        super().__init__(message or f"Workflow run '{run_id}' not found.")


class RailRuntimeError(RailError):
    """Base exception for workflow runtime execution errors."""


class RailWorkflowNotActiveError(RailRuntimeError):
    """Raised when an operation is attempted on a workflow run that is not active."""

    def __init__(self, run_id: str, status: str, message: Optional[str] = None) -> None:
        self.run_id = run_id
        self.status = status
        if message is None:
            if status == "completed":
                message = f"Workflow run '{run_id}' is already completed."
            elif status == "stopped":
                message = f"Workflow run '{run_id}' was stopped and is no longer active."
            elif status == "failed":
                message = f"Workflow run '{run_id}' has failed."
            else:
                message = f"Workflow run '{run_id}' is not active (status: '{status}')."
        super().__init__(message)


class RailHumanGateBlockedError(RailRuntimeError):
    """Raised when an agent attempts to complete or advance a step while blocked at a human gate."""

    def __init__(self, run_id: str, step_id: str, message: Optional[str] = None) -> None:
        self.run_id = run_id
        self.step_id = step_id
        default_msg = (
            f"Step '{step_id}' in run '{run_id}' is a human gate and cannot be completed by an agent. "
            "Execution is paused until resolved by human action."
        )
        super().__init__(message or default_msg)


class RailHumanGateNotActiveError(RailRuntimeError):
    """Raised when a human action is submitted but the workflow run is not paused on a human step."""

    def __init__(self, run_id: str, current_step: Optional[str], message: Optional[str] = None) -> None:
        self.run_id = run_id
        self.current_step = current_step
        default_msg = (
            f"Cannot resolve human action for run '{run_id}': active step is '{current_step}', "
            "which is not a human gate."
        )
        super().__init__(message or default_msg)


class RailInvalidResultError(RailRuntimeError):
    """Raised when an agent reports an invalid result for a choice step or reports a result on a linear step."""

    def __init__(
        self,
        step_id: str,
        result: Optional[str],
        allowed_options: Optional[list[str]] = None,
        message: Optional[str] = None,
    ) -> None:
        self.step_id = step_id
        self.result = result
        self.allowed_options = allowed_options or []
        if message:
            msg = message
        elif allowed_options:
            msg = f"Invalid choice result '{result}' for step '{step_id}'. Allowed options: {allowed_options}."
        else:
            msg = f"Step '{step_id}' does not accept a choice result."
        super().__init__(msg)


class RailInvalidActionError(RailRuntimeError):
    """Raised when an invalid action is submitted to resolve a human gate."""

    def __init__(
        self,
        step_id: str,
        action: str,
        allowed_actions: Optional[list[str]] = None,
        message: Optional[str] = None,
    ) -> None:
        self.step_id = step_id
        self.action = action
        self.allowed_actions = allowed_actions or []
        if message:
            msg = message
        else:
            msg = f"Invalid human action '{action}' for step '{step_id}'. Allowed actions: {self.allowed_actions}."
        super().__init__(msg)


class RailStepNotFoundError(RailRuntimeError):
    """Raised when a step cannot be found in the workflow definition."""

    def __init__(self, step_id: str, workflow_name: Optional[str] = None) -> None:
        self.step_id = step_id
        self.workflow_name = workflow_name
        wf_info = f" in workflow '{workflow_name}'" if workflow_name else ""
        super().__init__(f"Step '{step_id}' not found{wf_info}.")


class RailStepExecutionError(RailRuntimeError):
    """Raised when a step execution invariant is violated (e.g. step mismatch)."""
