"""Model Context Protocol (MCP) Server with JSON-RPC 2.0 stdio transport."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, TextIO, Union

from rail.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    CallToolResult,
    Implementation,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    ServerCapabilities,
)
from rail.mcp.tools import MCPToolHandler, get_tool_definitions
from rail.runtime import WorkflowRuntime

logger = logging.getLogger("rail.mcp")


class MCPServer:
    """Standard Model Context Protocol (MCP) server running over JSON-RPC 2.0 stdio transport."""

    def __init__(
        self,
        runtime: Optional[WorkflowRuntime] = None,
        workflows_dir: Optional[Union[str, Path]] = None,
        db_path: Optional[Union[str, Path]] = None,
        name: str = "rail",
        version: str = "0.1.0",
    ) -> None:
        if runtime is not None:
            self._runtime = runtime
            self._owns_runtime = False
        else:
            self._runtime = WorkflowRuntime(workflows_dir=workflows_dir, db_path=db_path)
            self._owns_runtime = True

        self.name = name
        self.version = version
        self.tool_handler = MCPToolHandler(self._runtime)
        self._tools = get_tool_definitions()

    @property
    def runtime(self) -> WorkflowRuntime:
        """Return underlying WorkflowRuntime."""
        return self._runtime

    def close(self) -> None:
        """Close server and underlying runtime if owned."""
        if self._owns_runtime:
            self._runtime.close()

    def __enter__(self) -> MCPServer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def handle_request(self, request_data: Union[str, Dict[str, Any]]) -> Optional[JSONRPCResponse]:
        """Process a single JSON-RPC request dict or JSON string, returning a JSONRPCResponse or None for notifications."""
        if isinstance(request_data, str):
            try:
                raw_dict = json.loads(request_data)
            except json.JSONDecodeError as exc:
                return JSONRPCResponse(
                    id=None,
                    error=JSONRPCError(code=PARSE_ERROR, message=f"Parse error: {exc}"),
                )
        else:
            raw_dict = request_data

        if not isinstance(raw_dict, dict):
            return JSONRPCResponse(
                id=None,
                error=JSONRPCError(code=INVALID_REQUEST, message="Invalid Request: expected JSON object"),
            )

        try:
            req = JSONRPCRequest.model_validate(raw_dict)
        except Exception as exc:
            msg_id = raw_dict.get("id") if isinstance(raw_dict, dict) else None
            return JSONRPCResponse(
                id=msg_id,
                error=JSONRPCError(code=INVALID_REQUEST, message=f"Invalid Request: {exc}"),
            )

        # Dispatch method
        method = req.method
        req_id = req.id
        params = req.params or {}

        try:
            if method == "initialize":
                result = InitializeResult(
                    protocolVersion="2024-11-05",
                    capabilities=ServerCapabilities(tools={"listChanged": False}),
                    serverInfo=Implementation(name=self.name, version=self.version),
                )
                return JSONRPCResponse(id=req_id, result=result.model_dump(exclude_none=True))

            elif method == "notifications/initialized":
                # Client acknowledgement notification
                return None

            elif method == "ping":
                return JSONRPCResponse(id=req_id, result={})

            elif method == "tools/list":
                result = ListToolsResult(tools=self._tools)
                return JSONRPCResponse(id=req_id, result=result.model_dump(exclude_none=True))

            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments") or {}

                if not tool_name:
                    return JSONRPCResponse(
                        id=req_id,
                        error=JSONRPCError(
                            code=INVALID_PARAMS,
                            message="Invalid params: 'name' is required for tools/call",
                        ),
                    )

                tool_result = self.tool_handler.execute_tool(name=tool_name, arguments=arguments)
                return JSONRPCResponse(id=req_id, result=tool_result.model_dump(exclude_none=True))

            else:
                if req.is_notification:
                    # Ignore unhandled notifications
                    return None
                return JSONRPCResponse(
                    id=req_id,
                    error=JSONRPCError(
                        code=METHOD_NOT_FOUND,
                        message=f"Method not found: '{method}'",
                    ),
                )

        except Exception as exc:
            logger.exception("Error handling MCP method %s", method)
            if req.is_notification:
                return None
            return JSONRPCResponse(
                id=req_id,
                error=JSONRPCError(
                    code=INTERNAL_ERROR,
                    message=f"Internal server error: {type(exc).__name__}: {exc}",
                ),
            )

    def run_stdio(self, stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> None:
        """Run standard I/O message loop reading line-delimited JSON-RPC from stdin."""
        in_stream = stdin or sys.stdin
        out_stream = stdout or sys.stdout

        for line in in_stream:
            line_str = line.strip()
            if not line_str:
                continue

            resp = self.handle_request(line_str)
            if resp is not None:
                resp_json = resp.model_dump_json(exclude_none=True)
                out_stream.write(resp_json + "\n")
                out_stream.flush()


def create_mcp_server(
    workflows_dir: Optional[Union[str, Path]] = None,
    db_path: Optional[Union[str, Path]] = None,
    runtime: Optional[WorkflowRuntime] = None,
) -> MCPServer:
    """Factory creating an MCP Server instance."""
    return MCPServer(runtime=runtime, workflows_dir=workflows_dir, db_path=db_path)


def run_mcp_server(
    workflows_dir: Optional[Union[str, Path]] = None,
    db_path: Optional[Union[str, Path]] = None,
    runtime: Optional[WorkflowRuntime] = None,
) -> None:
    """Run the MCP server reading from sys.stdin and writing to sys.stdout."""
    with create_mcp_server(workflows_dir=workflows_dir, db_path=db_path, runtime=runtime) as server:
        server.run_stdio()
