"""Runtime domain models for step inspection, status summaries, and transition results."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from rail.storage.models import RunStatus, StepHistoryRecord


class ActiveStepInfo(BaseModel):
    """Authoritative instruction and state inspection model for the current workflow step."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str = Field(description="Unique workflow run identifier")
    workflow_name: str = Field(description="Name of the executing workflow")
    task: str = Field(description="User task being executed")
    step_id: str = Field(description="Current active step identifier")
    step_type: str = Field(description="Step type: agent, human, or end")
    status: RunStatus = Field(description="Current run execution status")
    role: Optional[str] = Field(default=None, description="Execution role for agent steps (main, subagent)")
    name: Optional[str] = Field(default=None, description="Name for subagents")
    prompt: Optional[str] = Field(default=None, description="Authoritative prompt/instructions for agent steps")
    message: Optional[str] = Field(default=None, description="Instruction message for human gates")
    options: List[str] = Field(default_factory=list, description="Allowed choice options if step requires choice result")
    available_actions: List[str] = Field(default_factory=list, description="Available actions/transitions from this step")
    requires_human_action: bool = Field(default=False, description="Whether execution is paused waiting for human intervention")
    is_terminal: bool = Field(default=False, description="Whether this step represents workflow termination")

    def format_instructions(self) -> str:
        if self.step_type == "human":
            actions_text = "\n".join(f"- {action}" for action in self.available_actions)
            message = self.message.strip() if self.message else "Human gate requires resolution."
            return (
                f"Workflow paused\n\n"
                f"Current step: {self.step_id}\n"
                f"Type: human\n\n"
                f"{message}\n\n"
                f"Available actions:\n{actions_text}"
            )

        if self.step_type == "end":
            label = "Workflow completed" if self.status == RunStatus.COMPLETED else "Workflow stopped"
            return (
                f"{label}\n\n"
                f"Run: {self.run_id}\n"
                f"Current step: {self.step_id}\n"
                f"Type: end\n"
                f"Status: {self.status.value}"
            )

        lines = [
            f"Run: {self.run_id}",
            f"Workflow: {self.workflow_name}",
            f"Status: {self.status.value}",
            "",
            f"Current step: {self.step_id}",
            f"Type: {self.step_type}",
            f"Role: {self.role or 'main'}",
        ]
        if self.name:
            lines.append(f"Name: {self.name}")
        lines.extend(["", "Instructions:", self.prompt.strip() if self.prompt else ""])
        if self.options:
            lines.extend(["", "Allowed choice results:"])
            lines.extend(f"- {option}" for option in self.options)
        return "\n".join(lines)


class WorkflowRunStatus(BaseModel):
    """Detailed execution status summary for a workflow run."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str = Field(description="Unique workflow run identifier")
    workflow_name: str = Field(description="Name of the workflow")
    task: str = Field(description="User task being executed")
    status: RunStatus = Field(description="Current execution lifecycle status")
    current_step: Optional[str] = Field(default=None, description="Active step identifier")
    workspace_path: Optional[str] = Field(default=None, description="Associated workspace directory")
    completed_steps: List[str] = Field(default_factory=list, description="Chronological list of completed step IDs")
    pending_steps: List[str] = Field(default_factory=list, description="List of downstream pending step IDs")
    step_history: List[StepHistoryRecord] = Field(default_factory=list, description="Full chronological step execution history")
    created_at: str = Field(description="ISO 8601 UTC creation timestamp")
    updated_at: str = Field(description="ISO 8601 UTC last update timestamp")

    def format_status(self) -> str:
        lines = [
            f"Run: {self.run_id}",
            f"Workflow: {self.workflow_name}",
            f"Task: {self.task}",
            "",
            f"Status: {self.status.value}",
            "",
            "Current step:",
            self.current_step or "(none)",
            "",
            "Completed:",
        ]
        if self.completed_steps:
            lines.extend(f"✓ {step}" for step in self.completed_steps)
        else:
            lines.append("  (none)")

        lines.extend(["", "Current:"])
        if self.status in {RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED}:
            lines.append(f"  (none - {self.status.value})")
        elif self.current_step:
            lines.append(f"→ {self.current_step}")
        else:
            lines.append("  (none)")

        lines.extend(["", "Pending:"])
        if self.pending_steps and self.status in {RunStatus.RUNNING, RunStatus.PAUSED_HUMAN}:
            lines.extend(f"○ {step}" for step in self.pending_steps)
        else:
            lines.append("  (none)")
        return "\n".join(lines)


class StepTransitionResult(BaseModel):
    """Result returned upon completing a step or resolving a human gate."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str = Field(description="Associated workflow run identifier")
    previous_step_id: str = Field(description="Step ID that was just completed")
    current_step_id: str = Field(description="New active step ID after transition")
    transition_taken: Optional[str] = Field(default=None, description="Target step transitioned to")
    result: Optional[str] = Field(default=None, description="Reported choice outcome or human action")
    status: RunStatus = Field(description="Run status after transition")
    step_info: ActiveStepInfo = Field(description="Instruction and state info for the new active step")
