"""Persistence models for workflow runs and execution history."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    """Execution status of a workflow run."""

    RUNNING = "running"
    PAUSED_HUMAN = "paused_human"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


ACTIVE_RUN_STATUSES = (RunStatus.RUNNING.value, RunStatus.PAUSED_HUMAN.value)


class RunRecord(BaseModel):
    """Persistent database record representing a workflow run."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str = Field(description="Unique run identifier (e.g. R-000001)")
    workflow_name: str = Field(description="Name of the workflow being executed")
    task: str = Field(description="Natural language description of the requested task")
    status: RunStatus = Field(description="Current lifecycle status of the run")
    current_step: Optional[str] = Field(default=None, description="Active workflow step ID")
    workspace_path: Optional[str] = Field(
        default=None,
        description="Resolved path of the workspace/repository associated with the run",
    )
    created_at: str = Field(description="ISO 8601 UTC creation timestamp")
    updated_at: str = Field(description="ISO 8601 UTC last update timestamp")

    @property
    def is_active(self) -> bool:
        """Whether the workflow run is currently active (running or paused for human)."""
        return self.status in {RunStatus.RUNNING, RunStatus.PAUSED_HUMAN}


class StepHistoryRecord(BaseModel):
    """Persistent record of a single completed workflow step execution."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Unique auto-incrementing history entry identifier")
    run_id: str = Field(description="Associated workflow run identifier")
    step_id: str = Field(description="Step ID that was executed")
    step_type: str = Field(description="Type of step (agent, human, end)")
    role: Optional[str] = Field(default=None, description="Role executed for agent step")
    result: Optional[str] = Field(default=None, description="Result or human action reported")
    transition_taken: Optional[str] = Field(
        default=None, description="Target step transitioned to after this step"
    )
    started_at: str = Field(description="ISO 8601 UTC timestamp when step execution started")
    completed_at: str = Field(description="ISO 8601 UTC timestamp when step execution completed")
