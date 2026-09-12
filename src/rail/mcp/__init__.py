"""Rail Model Context Protocol (MCP) server package."""

from rail.mcp.protocol import (
    CallToolResult,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    TextContent,
    Tool,
    ToolInputSchema,
)
from rail.mcp.server import MCPServer, create_mcp_server, run_mcp_server
from rail.mcp.tools import MCPToolHandler, get_tool_definitions

__all__ = [
    "MCPServer",
    "create_mcp_server",
    "run_mcp_server",
    "MCPToolHandler",
    "get_tool_definitions",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCError",
    "InitializeResult",
    "ListToolsResult",
    "CallToolResult",
    "Tool",
    "ToolInputSchema",
    "TextContent",
]
