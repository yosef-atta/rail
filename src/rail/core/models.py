"""Domain models for Workflow Language v0.1."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    """Execution role for an agent step."""

    MAIN = "main"
    SUBAGENT = "subagent"


class ChoiceResult(BaseModel):
    """Predefined choice result schema for agent steps."""

    model_config = ConfigDict(extra="allow")

    type: Literal["choice"] = "choice"
    options: List[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    """An agent-executed step in the workflow."""

    model_config = ConfigDict(extra="allow")

    type: Literal["agent"] = "agent"
    role: Optional[Role] = None
    name: Optional[str] = None
    prompt: Optional[str] = None
    result: Optional[ChoiceResult] = None
    next: Optional[str] = None
    transitions: Optional[Dict[str, str]] = None


class HumanStep(BaseModel):
    """A human review gate requiring explicit user intervention."""

    model_config = ConfigDict(extra="allow")

    type: Literal["human"] = "human"
    message: Optional[str] = None
    transitions: Optional[Dict[str, str]] = None
    next: Optional[str] = None
    role: Optional[Any] = None
    prompt: Optional[str] = None
    name: Optional[str] = None
    result: Optional[Any] = None


class EndStep(BaseModel):
    """Marks successful workflow completion."""

    model_config = ConfigDict(extra="allow")

    type: Literal["end"] = "end"
    next: Optional[str] = None
    transitions: Optional[Dict[str, str]] = None
    prompt: Optional[str] = None
    message: Optional[str] = None
    role: Optional[Any] = None
    result: Optional[Any] = None


Step = Annotated[Union[AgentStep, HumanStep, EndStep], Field(discriminator="type")]


class Workflow(BaseModel):
    """Authoritative representation of a Rail Workflow definition."""

    model_config = ConfigDict(extra="allow")

    version: str
    name: str
    description: Optional[str] = None
    start: str
    steps: Dict[str, Step] = Field(default_factory=dict)
