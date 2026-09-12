"""Core workflow runtime and transition state machine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

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
from rail.core.loader import load_workflow
from rail.core.models import AgentStep, EndStep, HumanStep, Workflow
from rail.core.validator import validate_workflow
from rail.runtime.models import ActiveStepInfo, StepTransitionResult, WorkflowRunStatus
from rail.storage.models import ACTIVE_RUN_STATUSES, RunRecord, RunStatus, StepHistoryRecord
from rail.storage.store import StateStore, _now_utc_iso


class WorkflowRuntime:
    """Authoritative execution engine driving workflow runs and state transitions."""

    def __init__(
        self,
        store: Optional[StateStore] = None,
        workflows_dir: Optional[Union[str, Path]] = None,
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """Initialize workflow runtime.

        If store is omitted, initializes an internal StateStore (using optional db_path).
        """
        if store is not None:
            self._store = store
            self._owns_store = False
        else:
            self._store = StateStore(db_path=db_path)
            self._owns_store = True

        self.workflows_dir = Path(workflows_dir).resolve() if workflows_dir else None
        self._workflows: Dict[str, Workflow] = {}

    @property
    def store(self) -> StateStore:
        """Return the underlying StateStore."""
        return self._store

    def close(self) -> None:
        """Close the underlying StateStore if owned by this runtime instance."""
        if self._owns_store:
            self._store.close()

    def __enter__(self) -> WorkflowRuntime:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def register_workflow(self, workflow: Workflow) -> None:
        """Register an in-memory workflow definition for execution."""
        validate_workflow(workflow, raise_on_error=True)
        self._workflows[workflow.name] = workflow

    def get_workflow(self, workflow_name_or_path: Union[str, Path]) -> Workflow:
        """Retrieve a validated workflow definition, from registry or filesystem."""
        key = str(workflow_name_or_path)
        if key in self._workflows:
            return self._workflows[key]

        name_key = Path(workflow_name_or_path).stem
        if name_key in self._workflows:
            return self._workflows[name_key]

        wf = load_workflow(workflow_name_or_path, workflows_dir=self.workflows_dir, validate=True)
        self._workflows[wf.name] = wf
        return wf

    def start_run(
        self,
        workflow_name: Union[str, Path, Workflow],
        task: str,
        workspace_path: Optional[Union[str, Path]] = None,
        run_id: Optional[str] = None,
    ) -> ActiveStepInfo:
        """Initialize and start a new workflow run.

        Validates the workflow definition, persists the run record in the state store,
        activates the start step, and enforces start step invariants.
        """
        if isinstance(workflow_name, Workflow):
            workflow = workflow_name
            self.register_workflow(workflow)
        else:
            workflow = self.get_workflow(workflow_name)

        if not task or not task.strip():
            raise ValueError("task description cannot be empty")

        start_step_id = workflow.start
        if start_step_id not in workflow.steps:
            raise RailStepNotFoundError(start_step_id, workflow.name)

        start_step = workflow.steps[start_step_id]

        # 1. Create run in store
        run = self._store.create_run(
            workflow_name=workflow.name,
            task=task.strip(),
            current_step=start_step_id,
            workspace_path=workspace_path,
            run_id=run_id,
        )

        # 2. Check initial step type invariants
        if start_step.type == "human":
            run = self._store.update_run_status(run.run_id, RunStatus.PAUSED_HUMAN)
        elif start_step.type == "end":
            now_ts = _now_utc_iso()
            run = self._store.update_run_status(run.run_id, RunStatus.COMPLETED)
            self._store.record_step_completion(
                run_id=run.run_id,
                step_id=start_step_id,
                step_type="end",
                started_at=now_ts,
                completed_at=now_ts,
            )

        return self.get_active_step(run.run_id)

    def get_active_step(self, run_id: str) -> ActiveStepInfo:
        """Return authoritative instructions and inspection state for the current active step."""
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)

        workflow = self.get_workflow(run.workflow_name)

        if not run.current_step:
            raise RailStepNotFoundError("(none)", workflow.name)

        step = workflow.steps.get(run.current_step)
        if not step:
            raise RailStepNotFoundError(run.current_step, workflow.name)

        options: List[str] = []
        if step.type == "agent" and hasattr(step, "result") and step.result:
            options = list(step.result.options)

        available_actions: List[str] = []
        if hasattr(step, "transitions") and step.transitions:
            available_actions = list(step.transitions.keys())

        return ActiveStepInfo(
            run_id=run.run_id,
            workflow_name=workflow.name,
            task=run.task,
            step_id=run.current_step,
            step_type=step.type,
            status=run.status,
            role=step.role.value if (hasattr(step, "role") and step.role) else None,
            name=getattr(step, "name", None),
            prompt=getattr(step, "prompt", None),
            message=getattr(step, "message", None),
            options=options,
            available_actions=available_actions,
            requires_human_action=(step.type == "human"),
            is_terminal=(step.type == "end"),
        )

    def complete_step(
        self,
        run_id: str,
        step_id: Optional[str] = None,
        result: Optional[str] = None,
    ) -> StepTransitionResult:
        """Complete the currently active agent step and transition to the next step.

        Strictly enforces:
        - Inactive/completed/failed runs cannot be transitioned.
        - Human gates cannot be completed by agent calls.
        - Choice results must match declared options exactly.
        - Linear steps reject choice results.
        - Exactly one authoritative destination step is determined from workflow graph.
        """
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)

        # Invariant: Lifecycle status check
        if run.status == RunStatus.COMPLETED:
            raise RailWorkflowNotActiveError(run_id, run.status.value, f"Workflow run '{run_id}' is already completed.")
        if run.status == RunStatus.FAILED:
            raise RailWorkflowNotActiveError(run_id, run.status.value, f"Workflow run '{run_id}' has failed.")
        if run.status == RunStatus.PAUSED_HUMAN:
            raise RailHumanGateBlockedError(run_id, run.current_step or "")
        if not run.current_step:
            raise RailWorkflowNotActiveError(run_id, run.status.value, f"Workflow run '{run_id}' has no active step.")

        # Invariant: Step ID check if provided
        if step_id is not None and step_id != run.current_step:
            raise RailStepExecutionError(
                f"Step '{step_id}' is not the currently active step '{run.current_step}' for run '{run_id}'."
            )

        workflow = self.get_workflow(run.workflow_name)
        current_step_id = run.current_step
        step = workflow.steps.get(current_step_id)
        if not step:
            raise RailStepNotFoundError(current_step_id, workflow.name)

        # Invariant: Agent step only
        if step.type == "human":
            raise RailHumanGateBlockedError(run_id, current_step_id)
        if step.type == "end":
            raise RailWorkflowNotActiveError(
                run_id, run.status.value, f"Workflow run '{run_id}' has already reached end step '{current_step_id}'."
            )

        # Invariant: Choice vs Linear evaluation
        reported_result: Optional[str] = None
        target_step_id: str

        if hasattr(step, "result") and step.result is not None:
            allowed_options = step.result.options
            if result is None or not isinstance(result, str) or not result.strip():
                raise RailInvalidResultError(
                    step_id=current_step_id,
                    result=result,
                    allowed_options=allowed_options,
                    message=f"Step '{current_step_id}' requires a choice result from {allowed_options}, but none was provided.",
                )

            clean_result = result.strip()
            if clean_result not in allowed_options:
                raise RailInvalidResultError(
                    step_id=current_step_id,
                    result=clean_result,
                    allowed_options=allowed_options,
                )

            transitions = step.transitions or {}
            if clean_result not in transitions:
                raise RailStepExecutionError(
                    f"Choice '{clean_result}' has no transition target defined in step '{current_step_id}'."
                )

            target_step_id = transitions[clean_result]
            reported_result = clean_result
        else:
            # Linear step
            if result is not None:
                raise RailInvalidResultError(
                    step_id=current_step_id,
                    result=str(result),
                    message=f"Step '{current_step_id}' is a linear step and does not accept a choice result.",
                )

            if not step.next:
                raise RailStepExecutionError(f"Linear step '{current_step_id}' is missing a 'next' target.")

            target_step_id = step.next

        if target_step_id not in workflow.steps:
            raise RailStepNotFoundError(target_step_id, workflow.name)

        next_step = workflow.steps[target_step_id]

        # Calculate step timing
        history = self._store.get_step_history(run_id)
        started_at = history[-1].completed_at if history else run.created_at
        completed_at = _now_utc_iso()

        # Record completion of current step
        self._store.record_step_completion(
            run_id=run_id,
            step_id=current_step_id,
            step_type="agent",
            role=step.role.value if (hasattr(step, "role") and step.role) else None,
            result=reported_result,
            transition_taken=target_step_id,
            started_at=started_at,
            completed_at=completed_at,
        )

        # Advance run to target step
        if next_step.type == "human":
            self._store.update_run_step(
                run_id=run_id,
                current_step=target_step_id,
                status=RunStatus.PAUSED_HUMAN,
            )
            new_status = RunStatus.PAUSED_HUMAN
        elif next_step.type == "end":
            self._store.update_run_step(
                run_id=run_id,
                current_step=target_step_id,
                status=RunStatus.COMPLETED,
            )
            self._store.record_step_completion(
                run_id=run_id,
                step_id=target_step_id,
                step_type="end",
                started_at=completed_at,
                completed_at=completed_at,
            )
            new_status = RunStatus.COMPLETED
        else:
            self._store.update_run_step(
                run_id=run_id,
                current_step=target_step_id,
                status=RunStatus.RUNNING,
            )
            new_status = RunStatus.RUNNING

        active_info = self.get_active_step(run_id)
        return StepTransitionResult(
            run_id=run_id,
            previous_step_id=current_step_id,
            current_step_id=target_step_id,
            transition_taken=target_step_id,
            result=reported_result,
            status=new_status,
            step_info=active_info,
        )

    def resolve_human_action(self, run_id: str, action: str) -> StepTransitionResult:
        """Resolve an active human gate and advance the workflow run.

        Validates the human action against the human step's declared transitions,
        records the human action, unpauses execution, and moves to the target step.
        """
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)

        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            raise RailWorkflowNotActiveError(run_id, run.status.value)

        workflow = self.get_workflow(run.workflow_name)
        current_step_id = run.current_step
        if not current_step_id:
            raise RailWorkflowNotActiveError(run_id, run.status.value, "Run has no active step.")

        step = workflow.steps.get(current_step_id)
        if not step:
            raise RailStepNotFoundError(current_step_id, workflow.name)

        if step.type != "human":
            raise RailHumanGateNotActiveError(run_id=run_id, current_step=current_step_id)

        transitions = step.transitions or {}
        clean_action = str(action).strip() if action else ""
        if not clean_action or clean_action not in transitions:
            allowed = list(transitions.keys())
            raise RailInvalidActionError(
                step_id=current_step_id,
                action=action,
                allowed_actions=allowed,
            )

        target_step_id = transitions[clean_action]
        if target_step_id not in workflow.steps:
            raise RailStepNotFoundError(target_step_id, workflow.name)

        next_step = workflow.steps[target_step_id]

        history = self._store.get_step_history(run_id)
        started_at = history[-1].completed_at if history else run.created_at
        completed_at = _now_utc_iso()

        # Record human action in store
        self._store.record_human_action(
            run_id=run_id,
            step_id=current_step_id,
            action=clean_action,
            next_step=target_step_id,
            started_at=started_at,
            completed_at=completed_at,
        )

        if next_step.type == "end":
            self._store.update_run_status(run_id=run_id, status=RunStatus.COMPLETED)
            self._store.record_step_completion(
                run_id=run_id,
                step_id=target_step_id,
                step_type="end",
                started_at=completed_at,
                completed_at=completed_at,
            )
            new_status = RunStatus.COMPLETED
        elif next_step.type == "human":
            self._store.update_run_status(run_id=run_id, status=RunStatus.PAUSED_HUMAN)
            new_status = RunStatus.PAUSED_HUMAN
        else:
            new_status = RunStatus.RUNNING

        active_info = self.get_active_step(run_id)
        return StepTransitionResult(
            run_id=run_id,
            previous_step_id=current_step_id,
            current_step_id=target_step_id,
            transition_taken=target_step_id,
            result=clean_action,
            status=new_status,
            step_info=active_info,
        )

    def get_run_status(self, run_id: str) -> WorkflowRunStatus:
        """Return comprehensive workflow status including completed, current, and pending steps."""
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)

        history = self._store.get_step_history(run_id)
        completed_steps = [h.step_id for h in history if h.step_type != "end"]

        pending_steps: List[str] = []
        if run.status != RunStatus.COMPLETED and run.current_step:
            workflow = self.get_workflow(run.workflow_name)
            pending_steps = self._compute_downstream_pending_steps(
                workflow=workflow,
                current_step_id=run.current_step,
            )

        return WorkflowRunStatus(
            run_id=run.run_id,
            workflow_name=run.workflow_name,
            task=run.task,
            status=run.status,
            current_step=run.current_step,
            workspace_path=run.workspace_path,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            step_history=history,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    def _compute_downstream_pending_steps(
        self,
        workflow: Workflow,
        current_step_id: str,
    ) -> List[str]:
        """Compute ordered downstream pending steps from current step via BFS traversal."""
        pending: List[str] = []
        visited: Set[str] = {current_step_id}
        queue: List[str] = []

        curr = workflow.steps.get(current_step_id)
        if curr:
            if curr.next and curr.next in workflow.steps and curr.next not in visited:
                queue.append(curr.next)
            if curr.transitions:
                for target in curr.transitions.values():
                    if target in workflow.steps and target not in visited and target not in queue:
                        queue.append(target)

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            pending.append(node)

            step_def = workflow.steps.get(node)
            if not step_def:
                continue

            if step_def.next and step_def.next in workflow.steps and step_def.next not in visited:
                queue.append(step_def.next)
            if step_def.transitions:
                for target in step_def.transitions.values():
                    if target in workflow.steps and target not in visited and target not in queue:
                        queue.append(target)

        return pending

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Retrieve a run record by run_id."""
        return self._store.get_run(run_id)

    def get_step_history(self, run_id: str) -> List[StepHistoryRecord]:
        """Retrieve chronological step execution history for a run."""
        return self._store.get_step_history(run_id)

    def get_active_run_for_workspace(
        self,
        workspace_path: Optional[Union[str, Path]] = None,
    ) -> Optional[RunRecord]:
        """Find the active (running or paused_human) run for a workspace directory."""
        return self._store.get_active_run_for_workspace(workspace_path)

    def list_runs(
        self,
        workspace_path: Optional[Union[str, Path]] = None,
        status: Optional[Union[RunStatus, str]] = None,
        limit: int = 50,
    ) -> List[RunRecord]:
        """List workflow runs with optional filters."""
        return self._store.list_runs(workspace_path=workspace_path, status=status, limit=limit)


# Architectural Alias
WorkflowEngine = WorkflowRuntime
