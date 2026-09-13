"""Phase 5 MCP coverage for explicit stopped terminal outcomes."""

from pathlib import Path

from rail.core.models import Workflow
from rail.mcp.tools import MCPToolHandler
from rail.runtime import WorkflowRuntime
from rail.storage import StateStore


def test_mcp_complete_step_reports_stopped(tmp_path: Path):
    workflow = Workflow.model_validate(
        {
            "version": "0.1",
            "name": "agent-stop",
            "start": "review",
            "steps": {
                "review": {
                    "type": "agent",
                    "role": "main",
                    "prompt": "Review the implementation.",
                    "result": {"type": "choice", "options": ["approved", "rejected"]},
                    "transitions": {"approved": "done", "rejected": "stopped"},
                },
                "stopped": {"type": "end", "status": "stopped"},
                "done": {"type": "end"},
            },
        }
    )

    with StateStore(db_path=tmp_path / "rail.db") as store:
        runtime = WorkflowRuntime(store=store)
        runtime.register_workflow(workflow)
        step = runtime.start_run("agent-stop", task="Review task", workspace_path=tmp_path)
        result = MCPToolHandler(runtime).execute_tool(
            "workflow_complete_step",
            {"run_id": step.run_id, "result": "rejected"},
        )

        assert result.isError is False
        text = result.content[0].text
        assert "reached terminal step 'stopped' and STOPPED" in text
        assert "Workflow stopped" in text


def test_mcp_human_action_reports_stopped(tmp_path: Path):
    workflow = Workflow.model_validate(
        {
            "version": "0.1",
            "name": "human-stop",
            "start": "gate",
            "steps": {
                "gate": {
                    "type": "human",
                    "message": "Approve or stop.",
                    "transitions": {"approve": "done", "reject": "stopped"},
                },
                "stopped": {"type": "end", "status": "stopped"},
                "done": {"type": "end"},
            },
        }
    )

    with StateStore(db_path=tmp_path / "rail.db") as store:
        runtime = WorkflowRuntime(store=store)
        runtime.register_workflow(workflow)
        step = runtime.start_run("human-stop", task="Gate task", workspace_path=tmp_path)
        result = MCPToolHandler(runtime).execute_tool(
            "workflow_human_action",
            {"run_id": step.run_id, "action": "reject"},
        )

        assert result.isError is False
        text = result.content[0].text
        assert "reached terminal step 'stopped' and STOPPED" in text
        assert "Workflow stopped" in text


def test_mcp_workspace_lookup_without_run_returns_domain_error(tmp_path: Path):
    with StateStore(db_path=tmp_path / "rail.db") as store:
        runtime = WorkflowRuntime(store=store)
        result = MCPToolHandler(runtime).execute_tool(
            "workflow_status",
            {"workspace_path": str(tmp_path)},
        )

        assert result.isError is True
        text = result.content[0].text
        assert "No workflow run found for workspace" in text
        assert "Internal tool execution error" not in text
