"""Comprehensive protocol and tool integration tests for Phase 4: MCP Server & Tool Protocol Surface."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from rail.core.models import AgentStep, ChoiceResult, EndStep, HumanStep, Role, Workflow
from rail.mcp import (
    CallToolResult,
    InitializeResult,
    ListToolsResult,
    MCPServer,
    create_mcp_server,
)
from rail.mcp.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JSONRPCRequest,
    JSONRPCResponse,
)
from rail.runtime import WorkflowRuntime
from rail.storage import RunStatus, StateStore


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Return path to a temporary database file."""
    return tmp_path / "mcp_test.db"


@pytest.fixture
def store(temp_db_path: Path) -> StateStore:
    """Return an initialized StateStore using a temporary database."""
    with StateStore(temp_db_path) as s:
        yield s


@pytest.fixture
def runtime(store: StateStore, valid_fixtures_dir: Path) -> WorkflowRuntime:
    """Return a WorkflowRuntime instance configured with valid test fixtures."""
    rt = WorkflowRuntime(store=store, workflows_dir=valid_fixtures_dir)
    yield rt
    rt.close()


@pytest.fixture
def server(runtime: WorkflowRuntime) -> MCPServer:
    """Return an MCPServer instance wrapping the test runtime."""
    srv = MCPServer(runtime=runtime)
    yield srv
    srv.close()


# -----------------------------------------------------------------------------
# 1. MCP Standard Protocol Messages (initialize, ping, notifications, tools/list)
# -----------------------------------------------------------------------------


def test_mcp_initialize(server: MCPServer) -> None:
    """Verify MCP initialize handshake returns server info and capabilities."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp.id == 1
    assert resp.error is None
    assert resp.result is not None
    assert resp.result["protocolVersion"] == "2024-11-05"
    assert resp.result["serverInfo"]["name"] == "rail"
    assert "tools" in resp.result["capabilities"]


def test_mcp_notifications_and_ping(server: MCPServer) -> None:
    """Verify initialized notification returns None and ping returns empty object."""
    # Notification: no response expected
    init_notif = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    resp = server.handle_request(init_notif)
    assert resp is None

    # Ping
    ping_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "ping",
    }
    resp_ping = server.handle_request(ping_req)
    assert resp_ping is not None
    assert resp_ping.id == 2
    assert resp_ping.result == {}


def test_mcp_tools_list(server: MCPServer) -> None:
    """Verify tools/list exposes all 5 authoritative workflow tools."""
    req = {
        "jsonrpc": "2.0",
        "id": "list-1",
        "method": "tools/list",
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp.id == "list-1"
    assert resp.result is not None
    tools = resp.result["tools"]
    tool_names = [t["name"] for t in tools]

    assert "workflow_start" in tool_names
    assert "workflow_status" in tool_names
    assert "workflow_step" in tool_names
    assert "workflow_complete_step" in tool_names
    assert "workflow_human_action" in tool_names

    # Check input schemas
    start_tool = next(t for t in tools if t["name"] == "workflow_start")
    assert "workflow" in start_tool["inputSchema"]["properties"]
    assert "task" in start_tool["inputSchema"]["properties"]
    assert start_tool["inputSchema"]["required"] == ["workflow", "task"]


# -----------------------------------------------------------------------------
# 2. Tool Execution: workflow_start & workflow_status
# -----------------------------------------------------------------------------


def test_tool_workflow_start(server: MCPServer) -> None:
    """Verify workflow_start initializes a run and returns first step instructions."""
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "workflow_start",
            "arguments": {
                "workflow": "fast-fix",
                "task": "Fix null pointer",
                "run_id": "R-MCP001",
            },
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp.id == 10
    assert resp.error is None
    assert resp.result["isError"] is False
    text = resp.result["content"][0]["text"]
    assert "Started workflow run 'R-MCP001'" in text
    assert "Current step: fix" in text
    assert "Diagnose and fix the bug." in text


def test_tool_workflow_status(server: MCPServer) -> None:
    """Verify workflow_status provides accurate progress snapshot."""
    # Start run
    server.runtime.start_run("fast-fix", task="Status test", run_id="R-STAT1")

    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "workflow_status",
            "arguments": {
                "run_id": "R-STAT1",
            },
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp.result["isError"] is False
    text = resp.result["content"][0]["text"]
    assert "Run: R-STAT1" in text
    assert "Status: running" in text
    assert "Current step:\nfix" in text
    assert "Pending:\n○ test\n○ done" in text


# -----------------------------------------------------------------------------
# 3. Tool Execution: workflow_step & workflow_complete_step
# -----------------------------------------------------------------------------


def test_tool_workflow_step_and_complete_linear(server: MCPServer) -> None:
    """Verify linear step completion workflow (fix -> test -> done)."""
    server.runtime.start_run("fast-fix", task="Linear MCP test", run_id="R-LIN1")

    # Inspect active step
    step_req = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "workflow_step",
            "arguments": {"run_id": "R-LIN1"},
        },
    }
    step_resp = server.handle_request(step_req)
    assert "Current step: fix" in step_resp.result["content"][0]["text"]

    # Complete fix -> test
    comp_req1 = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {
            "name": "workflow_complete_step",
            "arguments": {"run_id": "R-LIN1", "step_id": "fix"},
        },
    }
    comp_resp1 = server.handle_request(comp_req1)
    assert comp_resp1.result["isError"] is False
    assert "Step 'fix' completed." in comp_resp1.result["content"][0]["text"]
    assert "Advanced to next step 'test'." in comp_resp1.result["content"][0]["text"]

    # Complete test -> done
    comp_req2 = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "workflow_complete_step",
            "arguments": {"run_id": "R-LIN1"},
        },
    }
    comp_resp2 = server.handle_request(comp_req2)
    assert comp_resp2.result["isError"] is False
    assert "reached terminal step 'done' and COMPLETED successfully" in comp_resp2.result["content"][0]["text"]


def test_tool_workflow_complete_choice_branching(server: MCPServer) -> None:
    """Verify choice branching on review step."""
    server.runtime.start_run("default", task="Choice MCP test", run_id="R-CHOICE")
    server.runtime.complete_step("R-CHOICE")  # plan -> review_plan

    # Complete review_plan with choice 'approved'
    req = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "workflow_complete_step",
            "arguments": {
                "run_id": "R-CHOICE",
                "result": "approved",
            },
        },
    }
    resp = server.handle_request(req)
    assert resp.result["isError"] is False
    assert "Step 'review_plan' completed." in resp.result["content"][0]["text"]
    assert "Advanced to next step 'implement'." in resp.result["content"][0]["text"]


# -----------------------------------------------------------------------------
# 4. Tool Execution: workflow_human_action & Gate Safety Guardrails
# -----------------------------------------------------------------------------


def test_tool_workflow_human_action(server: MCPServer) -> None:
    """Verify resolving human gate via workflow_human_action and blocking agent completion."""
    server.runtime.start_run("default", task="Human MCP test", run_id="R-HUMAN")
    # Advance to human_review
    server.runtime.complete_step("R-HUMAN")  # plan -> review_plan
    server.runtime.complete_step("R-HUMAN", result="approved")  # review_plan -> implement
    server.runtime.complete_step("R-HUMAN")  # implement -> verify
    server.runtime.complete_step("R-HUMAN")  # verify -> human_review (paused)

    # Agent attempting to complete human gate must fail with isError=True
    agent_try_req = {
        "jsonrpc": "2.0",
        "id": 40,
        "method": "tools/call",
        "params": {
            "name": "workflow_complete_step",
            "arguments": {"run_id": "R-HUMAN"},
        },
    }
    resp_blocked = server.handle_request(agent_try_req)
    assert resp_blocked.result["isError"] is True
    assert "human gate and cannot be completed by an agent" in resp_blocked.result["content"][0]["text"]

    # Human action resolves gate
    human_req = {
        "jsonrpc": "2.0",
        "id": 41,
        "method": "tools/call",
        "params": {
            "name": "workflow_human_action",
            "arguments": {
                "run_id": "R-HUMAN",
                "action": "approve",
            },
        },
    }
    resp_human = server.handle_request(human_req)
    assert resp_human.result["isError"] is False
    assert "Human action 'approve' recorded" in resp_human.result["content"][0]["text"]
    assert "COMPLETED successfully" in resp_human.result["content"][0]["text"]


# -----------------------------------------------------------------------------
# 5. Guardrails, Protocol Errors & Validation
# -----------------------------------------------------------------------------


def test_guardrail_invalid_choice_result(server: MCPServer) -> None:
    """Verify invalid choice result returns informative error with valid options."""
    server.runtime.start_run("default", task="Invalid choice test", run_id="R-INV1")
    server.runtime.complete_step("R-INV1")  # at review_plan

    req = {
        "jsonrpc": "2.0",
        "id": 50,
        "method": "tools/call",
        "params": {
            "name": "workflow_complete_step",
            "arguments": {
                "run_id": "R-INV1",
                "result": "almost_approved",
            },
        },
    }
    resp = server.handle_request(req)
    assert resp.result["isError"] is True
    text = resp.result["content"][0]["text"]
    assert "Invalid choice result 'almost_approved'" in text
    assert "approved" in text
    assert "changes_required" in text


def test_guardrail_linear_step_rejects_result(server: MCPServer) -> None:
    """Verify linear step rejects choice result parameter."""
    server.runtime.start_run("fast-fix", task="Linear reject test", run_id="R-INV2")

    req = {
        "jsonrpc": "2.0",
        "id": 51,
        "method": "tools/call",
        "params": {
            "name": "workflow_complete_step",
            "arguments": {
                "run_id": "R-INV2",
                "result": "approved",
            },
        },
    }
    resp = server.handle_request(req)
    assert resp.result["isError"] is True
    assert "linear step and does not accept a choice result" in resp.result["content"][0]["text"]


def test_guardrail_human_action_on_agent_step_rejected(server: MCPServer) -> None:
    """Verify workflow_human_action fails when step is an agent step."""
    server.runtime.start_run("fast-fix", task="Gate reject test", run_id="R-INV3")

    req = {
        "jsonrpc": "2.0",
        "id": 52,
        "method": "tools/call",
        "params": {
            "name": "workflow_human_action",
            "arguments": {
                "run_id": "R-INV3",
                "action": "approve",
            },
        },
    }
    resp = server.handle_request(req)
    assert resp.result["isError"] is True
    assert "not a human gate" in resp.result["content"][0]["text"]


def test_protocol_error_unknown_tool_and_method(server: MCPServer) -> None:
    """Verify unknown tool call and unknown JSON-RPC method handling."""
    # Unknown tool
    req_tool = {
        "jsonrpc": "2.0",
        "id": 60,
        "method": "tools/call",
        "params": {
            "name": "unknown_tool",
            "arguments": {},
        },
    }
    resp_tool = server.handle_request(req_tool)
    assert resp_tool.result["isError"] is True
    assert "Unknown tool: 'unknown_tool'" in resp_tool.result["content"][0]["text"]

    # Unknown JSON-RPC method
    req_method = {
        "jsonrpc": "2.0",
        "id": 61,
        "method": "non_existent_method",
    }
    resp_method = server.handle_request(req_method)
    assert resp_method.error is not None
    assert resp_method.error.code == METHOD_NOT_FOUND


def test_protocol_error_malformed_json_and_invalid_request(server: MCPServer) -> None:
    """Verify parse error and invalid request handling."""
    # Malformed JSON
    resp_parse = server.handle_request("{invalid_json: true")
    assert resp_parse is not None
    assert resp_parse.error.code == PARSE_ERROR

    # Invalid request structure (e.g. integer instead of dict)
    resp_invalid = server.handle_request(123)  # type: ignore
    assert resp_invalid is not None
    assert resp_invalid.error.code == INVALID_REQUEST


# -----------------------------------------------------------------------------
# 6. Stdio Loop Simulation
# -----------------------------------------------------------------------------


def test_stdio_message_loop(server: MCPServer) -> None:
    """Verify running stdio message loop reading and writing line-delimited JSON."""
    input_stream = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    output_stream = io.StringIO()

    server.run_stdio(stdin=input_stream, stdout=output_stream)
    output_lines = [line.strip() for line in output_stream.getvalue().splitlines() if line.strip()]

    assert len(output_lines) == 2

    res1 = json.loads(output_lines[0])
    assert res1["id"] == 1
    assert res1["result"] == {}

    res2 = json.loads(output_lines[1])
    assert res2["id"] == 2
    assert len(res2["result"]["tools"]) == 5


def test_create_mcp_server_factory(temp_db_path: Path, valid_fixtures_dir: Path) -> None:
    """Verify create_mcp_server factory initializes standalone server."""
    with create_mcp_server(workflows_dir=valid_fixtures_dir, db_path=temp_db_path) as srv:
        assert srv.runtime is not None
        step_res = srv.tool_handler.execute_tool(
            "workflow_start",
            {"workflow": "fast-fix", "task": "Factory test"},
        )
        assert step_res.isError is False
        assert "Started workflow run" in step_res.content[0].text
