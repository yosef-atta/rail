"""Comprehensive engine simulation tests for Phase 3: Workflow Runtime & Transition State Machine."""

from pathlib import Path
import pytest

from rail.core.exceptions import (
    RailHumanGateBlockedError,
    RailHumanGateNotActiveError,
    RailInvalidActionError,
    RailInvalidResultError,
    RailRunNotFoundError,
    RailStepExecutionError,
    RailStepNotFoundError,
    RailValidationError,
    RailWorkflowNotActiveError,
)
from rail.core.models import AgentStep, ChoiceResult, EndStep, HumanStep, Role, Workflow
from rail.runtime import (
    ActiveStepInfo,
    StepTransitionResult,
    WorkflowEngine,
    WorkflowRunStatus,
    WorkflowRuntime,
)
from rail.storage import RunStatus, StateStore


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Return path to a temporary database file."""
    return tmp_path / "runtime_test.db"


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


# -----------------------------------------------------------------------------
# 1. Run Lifecycle Engine Tests
# -----------------------------------------------------------------------------


def test_start_run_linear_workflow(runtime: WorkflowRuntime) -> None:
    """Verify starting a run loads, validates, persists, and activates the start step."""
    step_info = runtime.start_run("fast-fix", task="Fix null pointer exception")

    assert step_info.run_id == "R-000001"
    assert step_info.workflow_name == "fast-fix"
    assert step_info.task == "Fix null pointer exception"
    assert step_info.step_id == "fix"
    assert step_info.step_type == "agent"
    assert step_info.role == "main"
    assert step_info.status == RunStatus.RUNNING
    assert step_info.requires_human_action is False
    assert step_info.is_terminal is False
    assert "Diagnose and fix the bug." in (step_info.prompt or "")

    # Check instructions formatting
    formatted = step_info.format_instructions()
    assert "Run: R-000001" in formatted
    assert "Current step: fix" in formatted
    assert "Role: main" in formatted


def test_start_run_empty_task_raises(runtime: WorkflowRuntime) -> None:
    """Verify starting a run with an empty or whitespace task description is rejected."""
    with pytest.raises(ValueError, match="task description cannot be empty"):
        runtime.start_run("fast-fix", task="   ")


def test_start_run_invalid_workflow_raises(runtime: WorkflowRuntime, tmp_path: Path) -> None:
    """Verify starting a run with a statically invalid workflow fails validation immediately."""
    invalid_file = tmp_path / "invalid_wf.yaml"
    invalid_file.write_text(
        """
version: "0.1"
name: broken
start: non_existent
steps:
  fix:
    type: agent
    role: main
    prompt: fix
    next: fix
""",
        encoding="utf-8",
    )

    with pytest.raises(RailValidationError):
        runtime.start_run(invalid_file, task="Some task")


def test_subagent_step_inspection(runtime: WorkflowRuntime) -> None:
    """Verify active step inspection properly surfaces subagent role, name, and instructions."""
    runtime.start_run("default", task="Implement feature")
    # plan is current step. Complete it to reach review_plan (subagent)
    trans = runtime.complete_step("R-000001")
    step_info = trans.step_info

    assert step_info.step_id == "review_plan"
    assert step_info.step_type == "agent"
    assert step_info.role == "subagent"
    assert step_info.name == "plan-reviewer"
    assert step_info.options == ["approved", "changes_required"]

    formatted = step_info.format_instructions()
    assert "Role: subagent" in formatted
    assert "Name: plan-reviewer" in formatted
    assert "Allowed choice results:" in formatted
    assert "- approved" in formatted
    assert "- changes_required" in formatted


# -----------------------------------------------------------------------------
# 2. Linear Step Transitions
# -----------------------------------------------------------------------------


def test_linear_execution_from_start_to_end(runtime: WorkflowRuntime) -> None:
    """Verify linear execution from start to end (fast-fix: fix -> test -> done)."""
    step1 = runtime.start_run("fast-fix", task="Quick patch")
    assert step1.step_id == "fix"
    assert step1.status == RunStatus.RUNNING

    # 1. Complete fix -> advances to test
    trans1 = runtime.complete_step("R-000001", step_id="fix")
    assert trans1.previous_step_id == "fix"
    assert trans1.current_step_id == "test"
    assert trans1.status == RunStatus.RUNNING
    assert trans1.step_info.step_id == "test"

    # 2. Complete test -> advances to done (end step)
    trans2 = runtime.complete_step("R-000001", step_id="test")
    assert trans2.previous_step_id == "test"
    assert trans2.current_step_id == "done"
    assert trans2.status == RunStatus.COMPLETED
    assert trans2.step_info.is_terminal is True
    assert trans2.step_info.step_type == "end"

    # Invariant: Completed run cannot advance further
    with pytest.raises(RailWorkflowNotActiveError, match="already completed"):
        runtime.complete_step("R-000001")

    # Verify history recorded all three steps including end
    history = runtime.get_step_history("R-000001")
    assert len(history) == 3
    assert [h.step_id for h in history] == ["fix", "test", "done"]
    assert history[0].step_type == "agent"
    assert history[1].step_type == "agent"
    assert history[2].step_type == "end"


def test_linear_step_rejects_choice_result(runtime: WorkflowRuntime) -> None:
    """Verify agent reporting a choice result on a linear step is rejected."""
    runtime.start_run("fast-fix", task="Linear test")

    with pytest.raises(RailInvalidResultError, match="linear step and does not accept a choice result"):
        runtime.complete_step("R-000001", result="approved")


def test_complete_step_rejects_step_id_mismatch(runtime: WorkflowRuntime) -> None:
    """Verify complete_step rejects completion when step_id does not match active step."""
    runtime.start_run("fast-fix", task="Mismatch test")

    with pytest.raises(RailStepExecutionError, match="not the currently active step"):
        runtime.complete_step("R-000001", step_id="test")


# -----------------------------------------------------------------------------
# 3. Choice Results & Branching
# -----------------------------------------------------------------------------


def test_choice_result_approved_branch(runtime: WorkflowRuntime) -> None:
    """Verify reporting approved on review_plan branches to implement."""
    runtime.start_run("default", task="Implement auth")
    # Complete plan (linear)
    runtime.complete_step("R-000001")

    # Active step is review_plan (choice: approved, changes_required)
    curr = runtime.get_active_step("R-000001")
    assert curr.step_id == "review_plan"

    trans = runtime.complete_step("R-000001", result="approved")
    assert trans.previous_step_id == "review_plan"
    assert trans.current_step_id == "implement"
    assert trans.result == "approved"
    assert trans.status == RunStatus.RUNNING
    assert trans.step_info.step_id == "implement"


def test_choice_result_rejection_of_invalid_value(runtime: WorkflowRuntime) -> None:
    """Verify rejection of invalid choice values such as 'mostly_approved'."""
    runtime.start_run("default", task="Implement auth")
    runtime.complete_step("R-000001")  # at review_plan

    with pytest.raises(RailInvalidResultError) as exc_info:
        runtime.complete_step("R-000001", result="mostly_approved")

    assert "Invalid choice result 'mostly_approved'" in str(exc_info.value)
    assert "approved" in str(exc_info.value)
    assert "changes_required" in str(exc_info.value)

    # Active step must remain review_plan
    curr = runtime.get_active_step("R-000001")
    assert curr.step_id == "review_plan"


def test_choice_result_missing_raises(runtime: WorkflowRuntime) -> None:
    """Verify agent completing a choice step without providing a result is rejected."""
    runtime.start_run("default", task="Implement auth")
    runtime.complete_step("R-000001")  # at review_plan

    with pytest.raises(RailInvalidResultError, match="requires a choice result"):
        runtime.complete_step("R-000001", result=None)

    with pytest.raises(RailInvalidResultError, match="requires a choice result"):
        runtime.complete_step("R-000001", result="   ")


# -----------------------------------------------------------------------------
# 4. Multi-Iteration Loops & Cyclic Progression
# -----------------------------------------------------------------------------


def test_multi_iteration_review_and_fix_loops(runtime: WorkflowRuntime) -> None:
    """Verify multi-iteration review/fix loop records complete chronological history."""
    runtime.start_run("default", task="Loop test")
    run_id = "R-000001"

    # --- Iteration 1 ---
    runtime.complete_step(run_id)  # plan -> review_plan
    trans1 = runtime.complete_step(run_id, result="changes_required")  # review_plan -> plan
    assert trans1.current_step_id == "plan"
    assert trans1.result == "changes_required"

    # --- Iteration 2 ---
    runtime.complete_step(run_id)  # plan -> review_plan
    trans2 = runtime.complete_step(run_id, result="changes_required")  # review_plan -> plan
    assert trans2.current_step_id == "plan"

    # --- Iteration 3 ---
    runtime.complete_step(run_id)  # plan -> review_plan
    trans3 = runtime.complete_step(run_id, result="approved")  # review_plan -> implement
    assert trans3.current_step_id == "implement"
    assert trans3.result == "approved"

    # Inspect complete chronological iteration history
    history = runtime.get_step_history(run_id)
    assert len(history) == 6
    expected_sequence = [
        ("plan", None, "review_plan"),
        ("review_plan", "changes_required", "plan"),
        ("plan", None, "review_plan"),
        ("review_plan", "changes_required", "plan"),
        ("plan", None, "review_plan"),
        ("review_plan", "approved", "implement"),
    ]

    for hist, (exp_step, exp_result, exp_trans) in zip(history, expected_sequence):
        assert hist.step_id == exp_step
        assert hist.result == exp_result
        assert hist.transition_taken == exp_trans


# -----------------------------------------------------------------------------
# 5. Human Gate & Safety Invariants
# -----------------------------------------------------------------------------


def test_human_gate_blocking_and_resolution(runtime: WorkflowRuntime) -> None:
    """Verify runtime pauses at human gate, blocks agent advance, and unpauses via human action."""
    runtime.start_run("default", task="Human gate test")
    run_id = "R-000001"

    # Advance plan -> review_plan -> implement -> verify -> human_review
    runtime.complete_step(run_id)  # plan -> review_plan
    runtime.complete_step(run_id, result="approved")  # review_plan -> implement
    runtime.complete_step(run_id)  # implement -> verify

    # Completing verify transitions to human_review (HumanStep)
    trans = runtime.complete_step(run_id)
    assert trans.current_step_id == "human_review"
    assert trans.status == RunStatus.PAUSED_HUMAN
    assert trans.step_info.step_type == "human"
    assert trans.step_info.requires_human_action is True
    assert set(trans.step_info.available_actions) == {"approve", "changes_required"}

    # INVARIANT: Agent attempting complete_step is rejected
    with pytest.raises(RailHumanGateBlockedError) as exc_info:
        runtime.complete_step(run_id)
    assert "human gate and cannot be completed by an agent" in str(exc_info.value)

    # Rejection of invalid human action (e.g. 'reject' not in transitions)
    with pytest.raises(RailInvalidActionError) as act_exc:
        runtime.resolve_human_action(run_id, action="reject")
    assert "Invalid human action 'reject'" in str(act_exc.value)

    # Valid human action: 'changes_required' loops back to implement
    loop_trans = runtime.resolve_human_action(run_id, action="changes_required")
    assert loop_trans.current_step_id == "implement"
    assert loop_trans.status == RunStatus.RUNNING
    assert loop_trans.step_info.step_id == "implement"

    # Advance implement -> verify -> human_review again
    runtime.complete_step(run_id)  # implement -> verify
    runtime.complete_step(run_id)  # verify -> human_review
    assert runtime.get_active_step(run_id).status == RunStatus.PAUSED_HUMAN

    # Valid human action: 'approve' transitions to done and completes run
    done_trans = runtime.resolve_human_action(run_id, action="approve")
    assert done_trans.current_step_id == "done"
    assert done_trans.status == RunStatus.COMPLETED
    assert done_trans.step_info.step_type == "end"
    assert done_trans.step_info.is_terminal is True


def test_resolve_human_action_on_agent_step_raises(runtime: WorkflowRuntime) -> None:
    """Verify resolve_human_action fails when active step is not a human gate."""
    runtime.start_run("fast-fix", task="Gate test")
    run_id = "R-000001"

    with pytest.raises(RailHumanGateNotActiveError, match="not a human gate"):
        runtime.resolve_human_action(run_id, action="approve")


# -----------------------------------------------------------------------------
# 6. Status Inspector & Ordered Downstream Steps
# -----------------------------------------------------------------------------


def test_get_run_status_and_formatting(runtime: WorkflowRuntime) -> None:
    """Verify get_run_status computes completed, current, and ordered pending steps."""
    runtime.start_run("default", task="Status inspector test")
    run_id = "R-000001"

    # At start (plan)
    status0 = runtime.get_run_status(run_id)
    assert status0.status == RunStatus.RUNNING
    assert status0.current_step == "plan"
    assert status0.completed_steps == []
    assert "review_plan" in status0.pending_steps
    assert "implement" in status0.pending_steps
    assert "done" in status0.pending_steps

    # Complete plan -> at review_plan
    runtime.complete_step(run_id)
    status1 = runtime.get_run_status(run_id)
    assert status1.current_step == "review_plan"
    assert status1.completed_steps == ["plan"]
    assert "implement" in status1.pending_steps

    formatted = status1.format_status()
    assert "Run: R-000001" in formatted
    assert "Status: running" in formatted
    assert "Current step:\nreview_plan" in formatted
    assert "✓ plan" in formatted
    assert "→ review_plan" in formatted
    assert "○ implement" in formatted


def test_completed_workflow_status(runtime: WorkflowRuntime) -> None:
    """Verify status summary of a completed run shows no pending steps."""
    runtime.start_run("fast-fix", task="Fix bug")
    run_id = "R-000001"
    runtime.complete_step(run_id)  # fix -> test
    runtime.complete_step(run_id)  # test -> done

    status = runtime.get_run_status(run_id)
    assert status.status == RunStatus.COMPLETED
    assert status.current_step == "done"
    assert status.pending_steps == []

    formatted = status.format_status()
    assert "Status: completed" in formatted
    assert "(none - completed)" in formatted


# -----------------------------------------------------------------------------
# 7. Durability & State Recovery Across Restarts
# -----------------------------------------------------------------------------


def test_state_recovery_across_runtime_restart(
    temp_db_path: Path, valid_fixtures_dir: Path
) -> None:
    """Verify runtime state survives process/runtime close and re-open without state loss."""
    # 1. Start in runtime 1 and advance 2 steps
    with WorkflowRuntime(workflows_dir=valid_fixtures_dir, db_path=temp_db_path) as rt1:
        rt1.start_run("default", task="Durable task")
        rt1.complete_step("R-000001")  # plan -> review_plan
        rt1.complete_step("R-000001", result="approved")  # review_plan -> implement
        active = rt1.get_active_step("R-000001")
        assert active.step_id == "implement"

    # rt1 closed, SQLite connection terminated

    # 2. Re-open in fresh runtime 2 pointing to the same database
    with WorkflowRuntime(workflows_dir=valid_fixtures_dir, db_path=temp_db_path) as rt2:
        recovered_step = rt2.get_active_step("R-000001")
        assert recovered_step.step_id == "implement"
        assert recovered_step.status == RunStatus.RUNNING

        # Continue execution seamlessly in new instance
        trans = rt2.complete_step("R-000001")
        assert trans.current_step_id == "verify"


# -----------------------------------------------------------------------------
# 8. Workspace Active Run Inspection & Architectural Aliasing
# -----------------------------------------------------------------------------


def test_get_active_run_for_workspace(runtime: WorkflowRuntime, tmp_path: Path) -> None:
    """Verify get_active_run_for_workspace retrieves active run and handles completion."""
    ws = tmp_path / "my_project"
    ws.mkdir()

    assert runtime.get_active_run_for_workspace(ws) is None

    step = runtime.start_run("fast-fix", task="Workspace run", workspace_path=ws)
    active = runtime.get_active_run_for_workspace(ws)
    assert active is not None
    assert active.run_id == step.run_id
    assert active.is_active is True

    # Complete the run
    runtime.complete_step(step.run_id)
    runtime.complete_step(step.run_id)

    # No longer active
    assert runtime.get_active_run_for_workspace(ws) is None


def test_workflow_engine_alias() -> None:
    """Verify WorkflowEngine is an alias for WorkflowRuntime."""
    assert WorkflowEngine is WorkflowRuntime


# -----------------------------------------------------------------------------
# 9. In-Memory Registered Workflow Execution & Edge Cases
# -----------------------------------------------------------------------------


def test_in_memory_workflow_registration(runtime: WorkflowRuntime) -> None:
    """Verify in-memory dynamic workflows can be registered and executed."""
    custom_wf = Workflow(
        version="0.1",
        name="custom-dyn",
        start="step_a",
        steps={
            "step_a": AgentStep(
                type="agent",
                role=Role.MAIN,
                prompt="Do something custom",
                next="step_b",
            ),
            "step_b": EndStep(type="end"),
        },
    )

    runtime.register_workflow(custom_wf)
    step = runtime.start_run("custom-dyn", task="Dynamic task")
    assert step.step_id == "step_a"

    trans = runtime.complete_step(step.run_id)
    assert trans.current_step_id == "step_b"
    assert trans.status == RunStatus.COMPLETED


def test_start_step_as_human_gate(runtime: WorkflowRuntime) -> None:
    """Verify workflow whose start step is a human gate immediately pauses."""
    human_start_wf = Workflow(
        version="0.1",
        name="human-start",
        start="gate",
        steps={
            "gate": HumanStep(
                type="human",
                message="Confirm before starting.",
                transitions={"proceed": "finish"},
            ),
            "finish": EndStep(type="end"),
        },
    )

    runtime.register_workflow(human_start_wf)
    step = runtime.start_run("human-start", task="Gated start")
    assert step.step_id == "gate"
    assert step.status == RunStatus.PAUSED_HUMAN
    assert step.requires_human_action is True

    trans = runtime.resolve_human_action(step.run_id, action="proceed")
    assert trans.current_step_id == "finish"
    assert trans.status == RunStatus.COMPLETED


def test_runtime_store_property_and_get_run(runtime: WorkflowRuntime) -> None:
    """Verify runtime.store property and get_run / list_runs methods."""
    assert runtime.store is not None
    assert runtime.get_run("R-999999") is None

    step = runtime.start_run("fast-fix", task="Test run")
    run = runtime.get_run(step.run_id)
    assert run is not None
    assert run.run_id == step.run_id

    runs = runtime.list_runs(status=RunStatus.RUNNING)
    assert any(r.run_id == step.run_id for r in runs)


def test_non_existent_run_operations_raise(runtime: WorkflowRuntime) -> None:
    """Verify operations on a non-existent run_id raise RailRunNotFoundError."""
    missing_id = "R-999999"

    with pytest.raises(RailRunNotFoundError):
        runtime.get_active_step(missing_id)

    with pytest.raises(RailRunNotFoundError):
        runtime.complete_step(missing_id)

    with pytest.raises(RailRunNotFoundError):
        runtime.resolve_human_action(missing_id, action="approve")

    with pytest.raises(RailRunNotFoundError):
        runtime.get_run_status(missing_id)


def test_start_step_as_end_step(runtime: WorkflowRuntime) -> None:
    """Verify workflow that starts directly at an end step immediately completes."""
    end_start_wf = Workflow(
        version="0.1",
        name="end-start",
        start="terminal",
        steps={
            "terminal": EndStep(type="end"),
        },
    )

    runtime.register_workflow(end_start_wf)
    step = runtime.start_run("end-start", task="Instant complete")
    assert step.step_id == "terminal"
    assert step.status == RunStatus.COMPLETED
    assert step.is_terminal is True

    history = runtime.get_step_history(step.run_id)
    assert len(history) == 1
    assert history[0].step_id == "terminal"
    assert history[0].step_type == "end"


def test_human_to_human_transition(runtime: WorkflowRuntime) -> None:
    """Verify transition from one human gate to another human gate remains paused."""
    two_gates_wf = Workflow(
        version="0.1",
        name="two-gates",
        start="gate1",
        steps={
            "gate1": HumanStep(
                type="human",
                message="Gate 1 message",
                transitions={"pass1": "gate2"},
            ),
            "gate2": HumanStep(
                type="human",
                message="Gate 2 message",
                transitions={"pass2": "done"},
            ),
            "done": EndStep(type="end"),
        },
    )

    runtime.register_workflow(two_gates_wf)
    step = runtime.start_run("two-gates", task="Dual gate")
    assert step.step_id == "gate1"
    assert step.status == RunStatus.PAUSED_HUMAN

    # Resolve gate 1 -> transitions to gate 2 (remains paused_human)
    trans1 = runtime.resolve_human_action(step.run_id, action="pass1")
    assert trans1.current_step_id == "gate2"
    assert trans1.status == RunStatus.PAUSED_HUMAN
    assert trans1.step_info.requires_human_action is True

    # Resolve gate 2 -> transitions to done
    trans2 = runtime.resolve_human_action(step.run_id, action="pass2")
    assert trans2.current_step_id == "done"
    assert trans2.status == RunStatus.COMPLETED


def test_failed_run_invariants(runtime: WorkflowRuntime) -> None:
    """Verify completed and failed runs cannot be transitioned."""
    step = runtime.start_run("fast-fix", task="Failed test")
    # Manually simulate failing the run
    runtime.store.update_run_status(step.run_id, RunStatus.FAILED)

    with pytest.raises(RailWorkflowNotActiveError, match="failed"):
        runtime.complete_step(step.run_id)

    with pytest.raises(RailWorkflowNotActiveError):
        runtime.resolve_human_action(step.run_id, action="approve")


def test_formatting_instructions_and_status_edge_cases(runtime: WorkflowRuntime) -> None:
    """Verify instructions formatting for end steps and human steps with default messages."""
    step = runtime.start_run("fast-fix", task="Format test")
    runtime.complete_step(step.run_id)  # fix -> test
    trans = runtime.complete_step(step.run_id)  # test -> done

    # End step instruction formatting
    end_instr = trans.step_info.format_instructions()
    assert "Workflow completed" in end_instr
    assert "Type: end" in end_instr

    # Human step without custom message fallback
    info = ActiveStepInfo(
        run_id="R-000001",
        workflow_name="test",
        task="test",
        step_id="gate",
        step_type="human",
        status=RunStatus.PAUSED_HUMAN,
        message=None,
        available_actions=["ok"],
    )
    assert "Human gate requires resolution." in info.format_instructions()
    assert "- ok" in info.format_instructions()

    # Status formatting with empty completed and pending steps
    empty_status = WorkflowRunStatus(
        run_id="R-000001",
        workflow_name="test",
        task="test",
        status=RunStatus.RUNNING,
        current_step=None,
        completed_steps=[],
        pending_steps=[],
        created_at="2026-09-12T00:00:00Z",
        updated_at="2026-09-12T00:00:00Z",
    )
    fmt = empty_status.format_status()
    assert "Current step:\n(none)" in fmt
    assert "(none)" in fmt


def test_workflow_lookup_by_file_path(runtime: WorkflowRuntime, valid_fixtures_dir: Path) -> None:
    """Verify workflow lookup by file path and filename stem."""
    wf_path = valid_fixtures_dir / "default.yaml"
    step = runtime.start_run(wf_path, task="Lookup test")
    assert step.workflow_name == "default"
    assert step.step_id == "plan"

