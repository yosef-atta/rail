"""Unit tests for Rail domain models."""

import pytest
from pydantic import ValidationError

from rail.core.models import (
    AgentStep,
    ChoiceResult,
    EndStep,
    HumanStep,
    Role,
    Workflow,
)


def test_agent_step_instantiation():
    step = AgentStep(
        role=Role.MAIN,
        prompt="Implement feature",
        next="verify",
    )
    assert step.type == "agent"
    assert step.role == Role.MAIN
    assert step.prompt == "Implement feature"
    assert step.next == "verify"
    assert step.transitions is None


def test_agent_subagent_step():
    step = AgentStep(
        role=Role.SUBAGENT,
        name="plan-reviewer",
        prompt="Review plan",
        result=ChoiceResult(options=["approved", "changes_required"]),
        transitions={"approved": "implement", "changes_required": "plan"},
    )
    assert step.role == Role.SUBAGENT
    assert step.name == "plan-reviewer"
    assert step.result is not None
    assert step.result.type == "choice"
    assert step.result.options == ["approved", "changes_required"]


def test_human_step_instantiation():
    step = HumanStep(
        message="Please check the UI",
        transitions={"approve": "done", "reject": "fix"},
    )
    assert step.type == "human"
    assert step.message == "Please check the UI"
    assert step.transitions == {"approve": "done", "reject": "fix"}
    assert step.next is None


def test_end_step_instantiation():
    step = EndStep()
    assert step.type == "end"
    assert step.next is None
    assert step.transitions is None


def test_workflow_polymorphic_steps():
    data = {
        "version": "0.1",
        "name": "test-wf",
        "start": "step1",
        "steps": {
            "step1": {
                "type": "agent",
                "role": "main",
                "prompt": "Do work",
                "next": "step2",
            },
            "step2": {
                "type": "human",
                "message": "Verify work",
                "transitions": {"approve": "done"},
            },
            "done": {
                "type": "end",
            },
        },
    }
    wf = Workflow.model_validate(data)
    assert wf.version == "0.1"
    assert wf.name == "test-wf"
    assert wf.start == "step1"
    assert isinstance(wf.steps["step1"], AgentStep)
    assert isinstance(wf.steps["step2"], HumanStep)
    assert isinstance(wf.steps["done"], EndStep)


def test_workflow_invalid_discriminator_type():
    data = {
        "version": "0.1",
        "name": "test-wf",
        "start": "step1",
        "steps": {
            "step1": {
                "type": "unknown_type",
            }
        },
    }
    with pytest.raises(ValidationError):
        Workflow.model_validate(data)
