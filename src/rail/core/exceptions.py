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
