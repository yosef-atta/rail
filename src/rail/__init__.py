"""Rail - Lightweight workflow runtime for agentic coding tools."""

from rail.mcp import (
    MCPServer,
    create_mcp_server,
    run_mcp_server,
)
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
    "MCPServer",
    "RunRecord",
    "RunStatus",
    "StateStore",
    "StepHistoryRecord",
    "StepTransitionResult",
    "WorkflowEngine",
    "WorkflowRunStatus",
    "WorkflowRuntime",
    "__version__",
    "create_mcp_server",
    "run_mcp_server",
]
