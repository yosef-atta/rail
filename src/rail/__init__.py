"""Rail - Lightweight workflow runtime for agentic coding tools."""

from rail.runtime import (
    ActiveStepInfo,
    StepTransitionResult,
    WorkflowEngine,
    WorkflowRunStatus,
    WorkflowRuntime,
)
from rail.storage import (
    RunRecord,
    RunStatus,
    StateStore,
    StepHistoryRecord,
)

__version__ = "0.1.0"

__all__ = [
    "ActiveStepInfo",
    "RunRecord",
    "RunStatus",
    "StateStore",
    "StepHistoryRecord",
    "StepTransitionResult",
    "WorkflowEngine",
    "WorkflowRunStatus",
    "WorkflowRuntime",
    "__version__",
]
