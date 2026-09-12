"""Model Context Protocol (MCP) and JSON-RPC 2.0 protocol models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


# Standard JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

LATEST_PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05", "2024-10-07"]


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 Error object."""

    model_config = ConfigDict(extra="ignore")

    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 Request or Notification."""

    model_config = ConfigDict(extra="ignore")

    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = None

    @property
    def is_notification(self) -> bool:
        """Return True if this message is a notification (no id)."""
        return self.id is None


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 Response."""

    model_config = ConfigDict(extra="ignore")

    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


class Implementation(BaseModel):
    """Client/Server implementation info."""

    model_config = ConfigDict(extra="ignore")

    name: str
    version: str


class ServerCapabilities(BaseModel):
    """Capabilities advertised by MCP server."""

    model_config = ConfigDict(extra="ignore")

    tools: Optional[Dict[str, bool]] = Field(default_factory=lambda: {"listChanged": False})


class InitializeResult(BaseModel):
    """Result of an MCP initialize request."""

    model_config = ConfigDict(extra="ignore")

    protocolVersion: str = LATEST_PROTOCOL_VERSION
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)
    serverInfo: Implementation = Field(
        default_factory=lambda: Implementation(name="rail", version="0.1.0")
    )


class ToolInputSchema(BaseModel):
    """JSON Schema defining tool arguments."""

    model_config = ConfigDict(extra="ignore")

    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class Tool(BaseModel):
    """MCP Tool definition."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    inputSchema: ToolInputSchema


class ListToolsResult(BaseModel):
    """Result of tools/list request."""

    model_config = ConfigDict(extra="ignore")

    tools: List[Tool]


class TextContent(BaseModel):
    """Text content returned from tool execution."""

    model_config = ConfigDict(extra="ignore")

    type: str = "text"
    text: str


class CallToolResult(BaseModel):
    """Result of tools/call request."""

    model_config = ConfigDict(extra="ignore")

    content: List[TextContent] = Field(default_factory=list)
    isError: bool = False
