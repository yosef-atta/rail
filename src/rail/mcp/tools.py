"""Model Context Protocol (MCP) Tool handlers for Rail runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from rail.core.exceptions import (
    RailHumanGateBlockedError,
    RailHumanGateNotActiveError,
    RailInvalidActionError,
    RailInvalidResultError,
    RailRunNotFoundError,
    RailRuntimeError,
    RailStepExecutionError,
    RailStepNotFoundError,
    RailValidationError,
    RailWorkflowNotActiveError,
    RailWorkflowNotFoundError,
    RailWorkflowParseError,
)
from rail.mcp.protocol import CallToolResult, TextContent, Tool, ToolInputSchema
from rail.runtime import WorkflowRuntime
from rail.storage.models import RunStatus


def get_tool_definitions() -> List[Tool]:
    """Return list of standard MCP tool definitions for Rail."""
    return [
        Tool(
            name="workflow_start",
            description=(
                "Start a new workflow run with a specified workflow name or file and task description. "
                "Returns the authoritative instructions and metadata for the initial step."
            ),
            inputSchema=ToolInputSchema(
                properties={
                    "workflow": {
                        "type": "string",
                        "description": "Workflow name (for example 'default-human') or path to a workflow YAML file.",
                    },
                    "task": {
                        "type": "string",
                        "description": "Description of the user task or problem to be executed.",
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Optional workspace root directory path. Defaults to current working directory.",
                    },
                    "run_id": {
                        "type": "string",
                        "description": "Optional explicit run identifier (for example 'R-000001'). Generated automatically if omitted.",
                    },
                },
                required=["workflow", "task"],
            ),
        ),
        Tool(
            name="workflow_status",
            description=(
                "Get execution status and step history of a workflow run. "
                "Shows the active step, completed steps, and downstream pending steps."
            ),
            inputSchema=ToolInputSchema(
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Optional run identifier. If omitted, uses the active run in the workspace.",
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Optional workspace path to look up the active run if run_id is omitted.",
                    },
                },
                required=[],
            ),
        ),
        Tool(
            name="workflow_step",
            description="Get authoritative instructions, role, prompt, and options for the current workflow step.",
            inputSchema=ToolInputSchema(
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Optional run identifier. If omitted, uses the active run in the workspace.",
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Optional workspace path to look up the active run if run_id is omitted.",
                    },
                },
                required=[],
            ),
        ),
        Tool(
            name="workflow_complete_step",
            description=(
                "Report completion of the current active agent step and transition to the next step. "
                "For branching steps, 'result' must match one of the declared options. "
                "Linear steps must omit 'result'."
            ),
            inputSchema=ToolInputSchema(
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Optional run identifier. If omitted, uses the active run in the workspace.",
                    },
                    "step_id": {
                        "type": "string",
                        "description": "Optional current step ID to verify before transitioning.",
                    },
                    "result": {
                        "type": "string",
                        "description": "Choice result for a branching step. Omit for linear steps.",
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Optional workspace path to look up the active run if run_id is omitted.",
                    },
                },
                required=[],
            ),
        ),
        Tool(
            name="workflow_human_action",
            description="Resolve a paused human gate with a user-specified action to resume workflow execution.",
            inputSchema=ToolInputSchema(
                properties={
                    "action": {
                        "type": "string",
                        "description": "Human action chosen. Must match one of the actions declared by the human step.",
                    },
                    "run_id": {
                        "type": "string",
                        "description": "Optional run identifier. If omitted, uses the active paused run in the workspace.",
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Optional workspace path to look up the active run if run_id is omitted.",
                    },
                },
                required=["action"],
            ),
        ),
    ]


def _resolve_run_id(
    runtime: WorkflowRuntime,
    run_id: Optional[str] = None,
    workspace_path: Optional[str] = None,
) -> str:
    """Resolve an explicit run_id or look up the relevant run for a workspace."""
    if run_id and run_id.strip():
        return run_id.strip()

    workspace = Path(workspace_path).resolve() if workspace_path else Path.cwd().resolve()
    active_run = runtime.get_active_run_for_workspace(workspace)
    if active_run:
        return active_run.run_id

    # Inspection remains useful immediately after a run reaches a terminal state.
    runs = runtime.list_runs(workspace_path=workspace, limit=1)
    if runs:
        return runs[0].run_id

    raise RailRunNotFoundError(
        run_id or "(none)",
        f"No workflow run found for workspace '{workspace}'. Start a run with workflow_start.",
    )


class MCPToolHandler:
    """Execute MCP tool requests against an underlying WorkflowRuntime instance."""

    def __init__(self, runtime: WorkflowRuntime) -> None:
        self.runtime = runtime

    def execute_tool(self, name: str, arguments: Optional[Dict[str, Any]]) -> CallToolResult:
        """Dispatch and execute an MCP tool by name."""
        args = arguments or {}

        try:
            if name == "workflow_start":
                return self._tool_workflow_start(args)
            if name == "workflow_status":
                return self._tool_workflow_status(args)
            if name == "workflow_step":
                return self._tool_workflow_step(args)
            if name == "workflow_complete_step":
                return self._tool_workflow_complete_step(args)
            if name == "workflow_human_action":
                return self._tool_workflow_human_action(args)
            return CallToolResult(
                isError=True,
                content=[TextContent(text=f"Unknown tool: '{name}'")],
            )
        except (
            RailHumanGateBlockedError,
            RailHumanGateNotActiveError,
            RailInvalidActionError,
            RailInvalidResultError,
            RailRunNotFoundError,
            RailStepExecutionError,
            RailStepNotFoundError,
            RailValidationError,
            RailWorkflowNotActiveError,
            RailWorkflowNotFoundError,
            RailWorkflowParseError,
            RailRuntimeError,
            ValueError,
        ) as exc:
            return CallToolResult(isError=True, content=[TextContent(text=f"Error: {exc}")])
        except Exception as exc:
            return CallToolResult(
                isError=True,
                content=[TextContent(text=f"Internal tool execution error: {type(exc).__name__}: {exc}")],
            )

    def _tool_workflow_start(self, args: Dict[str, Any]) -> CallToolResult:
        workflow = args.get("workflow")
        if not workflow or not str(workflow).strip():
            return CallToolResult(isError=True, content=[TextContent(text="Error: 'workflow' parameter is required.")])

        task = args.get("task")
        if not task or not str(task).strip():
            return CallToolResult(
                isError=True,
                content=[TextContent(text="Error: 'task' parameter is required and cannot be empty.")],
            )

        step_info = self.runtime.start_run(
            workflow_name=str(workflow).strip(),
            task=str(task).strip(),
            workspace_path=args.get("workspace_path"),
            run_id=args.get("run_id"),
        )
        output_text = (
            f"Started workflow run '{step_info.run_id}' for workflow '{step_info.workflow_name}'.\n\n"
            f"{step_info.format_instructions()}"
        )
        return CallToolResult(isError=False, content=[TextContent(text=output_text)])

    def _tool_workflow_status(self, args: Dict[str, Any]) -> CallToolResult:
        run_id = _resolve_run_id(
            self.runtime,
            run_id=args.get("run_id"),
            workspace_path=args.get("workspace_path"),
        )
        status_info = self.runtime.get_run_status(run_id)
        return CallToolResult(isError=False, content=[TextContent(text=status_info.format_status())])

    def _tool_workflow_step(self, args: Dict[str, Any]) -> CallToolResult:
        run_id = _resolve_run_id(
            self.runtime,
            run_id=args.get("run_id"),
            workspace_path=args.get("workspace_path"),
        )
        step_info = self.runtime.get_active_step(run_id)
        return CallToolResult(isError=False, content=[TextContent(text=step_info.format_instructions())])

    def _tool_workflow_complete_step(self, args: Dict[str, Any]) -> CallToolResult:
        run_id = _resolve_run_id(
            self.runtime,
            run_id=args.get("run_id"),
            workspace_path=args.get("workspace_path"),
        )
        transition = self.runtime.complete_step(
            run_id=run_id,
            step_id=args.get("step_id"),
            result=args.get("result"),
        )

        step_info = transition.step_info
        if transition.status == RunStatus.COMPLETED:
            output_text = (
                f"Step '{transition.previous_step_id}' completed.\n"
                f"Workflow run '{run_id}' reached terminal step '{transition.current_step_id}' and COMPLETED successfully."
            )
        elif transition.status == RunStatus.STOPPED:
            output_text = (
                f"Step '{transition.previous_step_id}' completed.\n"
                f"Workflow run '{run_id}' reached terminal step '{transition.current_step_id}' and STOPPED.\n\n"
                f"{step_info.format_instructions()}"
            )
        elif transition.status == RunStatus.PAUSED_HUMAN:
            output_text = (
                f"Step '{transition.previous_step_id}' completed.\n"
                f"Transitioned to human gate '{transition.current_step_id}'. Workflow is PAUSED waiting for human action.\n\n"
                f"{step_info.format_instructions()}"
            )
        else:
            output_text = (
                f"Step '{transition.previous_step_id}' completed.\n"
                f"Advanced to next step '{transition.current_step_id}'.\n\n"
                f"{step_info.format_instructions()}"
            )

        return CallToolResult(isError=False, content=[TextContent(text=output_text)])

    def _tool_workflow_human_action(self, args: Dict[str, Any]) -> CallToolResult:
        action = args.get("action")
        if not action or not str(action).strip():
            return CallToolResult(
                isError=True,
                content=[TextContent(text="Error: 'action' parameter is required to resolve a human gate.")],
            )

        run_id = _resolve_run_id(
            self.runtime,
            run_id=args.get("run_id"),
            workspace_path=args.get("workspace_path"),
        )
        transition = self.runtime.resolve_human_action(run_id=run_id, action=str(action).strip())
        step_info = transition.step_info

        if transition.status == RunStatus.COMPLETED:
            output_text = (
                f"Human action '{action}' recorded for gate '{transition.previous_step_id}'.\n"
                f"Workflow run '{run_id}' reached terminal step '{transition.current_step_id}' and COMPLETED successfully."
            )
        elif transition.status == RunStatus.STOPPED:
            output_text = (
                f"Human action '{action}' recorded for gate '{transition.previous_step_id}'.\n"
                f"Workflow run '{run_id}' reached terminal step '{transition.current_step_id}' and STOPPED.\n\n"
                f"{step_info.format_instructions()}"
            )
        elif transition.status == RunStatus.PAUSED_HUMAN:
            output_text = (
                f"Human action '{action}' recorded for gate '{transition.previous_step_id}'.\n"
                f"Transitioned to next human gate '{transition.current_step_id}'. Workflow remains PAUSED.\n\n"
                f"{step_info.format_instructions()}"
            )
        else:
            output_text = (
                f"Human action '{action}' recorded for gate '{transition.previous_step_id}'.\n"
                f"Resumed execution at step '{transition.current_step_id}'.\n\n"
                f"{step_info.format_instructions()}"
            )

        return CallToolResult(isError=False, content=[TextContent(text=output_text)])
