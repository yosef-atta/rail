"""Core workflow runtime and transition state machine."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from rail.core.exceptions import (
    RailHumanGateBlockedError,
    RailHumanGateNotActiveError,
    RailInvalidActionError,
    RailInvalidResultError,
    RailRunNotFoundError,
    RailStepExecutionError,
    RailStepNotFoundError,
    RailWorkflowNotActiveError,
)
from rail.core.loader import load_workflow
from rail.core.models import EndStep, Workflow
from rail.core.validator import validate_workflow
from rail.runtime.models import ActiveStepInfo, StepTransitionResult, WorkflowRunStatus
from rail.storage.models import RunRecord, RunStatus, StepHistoryRecord
from rail.storage.store import StateStore, _now_utc_iso


class WorkflowRuntime:
    """Authoritative execution engine driving workflow runs and state transitions."""

    def __init__(
        self,
        store: Optional[StateStore] = None,
        workflows_dir: Optional[Union[str, Path]] = None,
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
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
        return self._store

    def close(self) -> None:
        if self._owns_store:
            self._store.close()

    def __enter__(self) -> "WorkflowRuntime":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def register_workflow(self, workflow: Workflow) -> None:
        validate_workflow(workflow, raise_on_error=True)
        self._workflows[workflow.name] = workflow

    def get_workflow(self, workflow_name_or_path: Union[str, Path]) -> Workflow:
        key = str(workflow_name_or_path)
        if key in self._workflows:
            return self._workflows[key]
        name_key = Path(workflow_name_or_path).stem
        if name_key in self._workflows:
            return self._workflows[name_key]
        workflow = load_workflow(workflow_name_or_path, workflows_dir=self.workflows_dir, validate=True)
        self._workflows[workflow.name] = workflow
        return workflow

    @staticmethod
    def _terminal_run_status(step: EndStep) -> RunStatus:
        return RunStatus.STOPPED if step.status.value == "stopped" else RunStatus.COMPLETED

    def _record_terminal_step(self, run_id: str, step_id: str, step: EndStep, timestamp: str) -> RunStatus:
        status = self._terminal_run_status(step)
        self._store.update_run_step(run_id=run_id, current_step=step_id, status=status)
        self._store.record_step_completion(
            run_id=run_id,
            step_id=step_id,
            step_type="end",
            result=step.status.value,
            started_at=timestamp,
            completed_at=timestamp,
        )
        return status

    def start_run(
        self,
        workflow_name: Union[str, Path, Workflow],
        task: str,
        workspace_path: Optional[Union[str, Path]] = None,
        run_id: Optional[str] = None,
    ) -> ActiveStepInfo:
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

        run = self._store.create_run(
            workflow_name=workflow.name,
            task=task.strip(),
            current_step=start_step_id,
            workspace_path=workspace_path,
            run_id=run_id,
        )

        if start_step.type == "human":
            self._store.update_run_status(run.run_id, RunStatus.PAUSED_HUMAN)
        elif start_step.type == "end":
            self._record_terminal_step(run.run_id, start_step_id, start_step, _now_utc_iso())

        return self.get_active_step(run.run_id)

    def get_active_step(self, run_id: str) -> ActiveStepInfo:
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
        if step.type == "agent" and step.result:
            options = list(step.result.options)
        transitions = getattr(step, "transitions", None)

        return ActiveStepInfo(
            run_id=run.run_id,
            workflow_name=workflow.name,
            task=run.task,
            step_id=run.current_step,
            step_type=step.type,
            status=run.status,
            role=step.role.value if getattr(step, "role", None) else None,
            name=getattr(step, "name", None),
            prompt=getattr(step, "prompt", None),
            message=getattr(step, "message", None),
            options=options,
            available_actions=list(transitions.keys()) if transitions else [],
            requires_human_action=(step.type == "human"),
            is_terminal=(step.type == "end"),
        )

    def complete_step(
        self,
        run_id: str,
        step_id: Optional[str] = None,
        result: Optional[str] = None,
    ) -> StepTransitionResult:
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)
        if run.status in {RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED}:
            raise RailWorkflowNotActiveError(run_id, run.status.value)
        if run.status == RunStatus.PAUSED_HUMAN:
            raise RailHumanGateBlockedError(run_id, run.current_step or "")
        if not run.current_step:
            raise RailWorkflowNotActiveError(run_id, run.status.value, f"Workflow run '{run_id}' has no active step.")
        if step_id is not None and step_id != run.current_step:
            raise RailStepExecutionError(
                f"Step '{step_id}' is not the currently active step '{run.current_step}' for run '{run_id}'."
            )

        workflow = self.get_workflow(run.workflow_name)
        current_step_id = run.current_step
        step = workflow.steps.get(current_step_id)
        if not step:
            raise RailStepNotFoundError(current_step_id, workflow.name)
        if step.type == "human":
            raise RailHumanGateBlockedError(run_id, current_step_id)
        if step.type == "end":
            raise RailWorkflowNotActiveError(run_id, run.status.value)

        reported_result: Optional[str] = None
        if step.result is not None:
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
                raise RailInvalidResultError(step_id=current_step_id, result=clean_result, allowed_options=allowed_options)
            transitions = step.transitions or {}
            if clean_result not in transitions:
                raise RailStepExecutionError(f"Choice '{clean_result}' has no transition target defined in step '{current_step_id}'.")
            target_step_id = transitions[clean_result]
            reported_result = clean_result
        else:
            if result is not None:
                raise RailInvalidResultError(
                    step_id=current_step_id,
                    result=str(result),
                    message=f"Step '{current_step_id}' is a linear step and does not accept a choice result.",
                )
            if not step.next:
                raise RailStepExecutionError(f"Linear step '{current_step_id}' is missing a 'next' target.")
            target_step_id = step.next

        next_step = workflow.steps.get(target_step_id)
        if not next_step:
            raise RailStepNotFoundError(target_step_id, workflow.name)

        history = self._store.get_step_history(run_id)
        started_at = history[-1].completed_at if history else run.created_at
        completed_at = _now_utc_iso()
        self._store.record_step_completion(
            run_id=run_id,
            step_id=current_step_id,
            step_type="agent",
            role=step.role.value if step.role else None,
            result=reported_result,
            transition_taken=target_step_id,
            started_at=started_at,
            completed_at=completed_at,
        )

        if next_step.type == "human":
            self._store.update_run_step(run_id, target_step_id, RunStatus.PAUSED_HUMAN)
            new_status = RunStatus.PAUSED_HUMAN
        elif next_step.type == "end":
            new_status = self._record_terminal_step(run_id, target_step_id, next_step, completed_at)
        else:
            self._store.update_run_step(run_id, target_step_id, RunStatus.RUNNING)
            new_status = RunStatus.RUNNING

        return StepTransitionResult(
            run_id=run_id,
            previous_step_id=current_step_id,
            current_step_id=target_step_id,
            transition_taken=target_step_id,
            result=reported_result,
            status=new_status,
            step_info=self.get_active_step(run_id),
        )

    def resolve_human_action(self, run_id: str, action: str) -> StepTransitionResult:
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)
        if run.status in {RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED}:
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
            raise RailInvalidActionError(step_id=current_step_id, action=action, allowed_actions=list(transitions))

        target_step_id = transitions[clean_action]
        next_step = workflow.steps.get(target_step_id)
        if not next_step:
            raise RailStepNotFoundError(target_step_id, workflow.name)

        history = self._store.get_step_history(run_id)
        started_at = history[-1].completed_at if history else run.created_at
        completed_at = _now_utc_iso()
        self._store.record_human_action(
            run_id=run_id,
            step_id=current_step_id,
            action=clean_action,
            next_step=target_step_id,
            started_at=started_at,
            completed_at=completed_at,
        )

        if next_step.type == "end":
            new_status = self._record_terminal_step(run_id, target_step_id, next_step, completed_at)
        elif next_step.type == "human":
            self._store.update_run_step(run_id, target_step_id, RunStatus.PAUSED_HUMAN)
            new_status = RunStatus.PAUSED_HUMAN
        else:
            self._store.update_run_step(run_id, target_step_id, RunStatus.RUNNING)
            new_status = RunStatus.RUNNING

        return StepTransitionResult(
            run_id=run_id,
            previous_step_id=current_step_id,
            current_step_id=target_step_id,
            transition_taken=target_step_id,
            result=clean_action,
            status=new_status,
            step_info=self.get_active_step(run_id),
        )

    def get_run_status(self, run_id: str) -> WorkflowRunStatus:
        run = self._store.get_run(run_id)
        if not run:
            raise RailRunNotFoundError(run_id)
        history = self._store.get_step_history(run_id)
        completed_steps = [history_step.step_id for history_step in history if history_step.step_type != "end"]
        pending_steps: List[str] = []
        if run.status in {RunStatus.RUNNING, RunStatus.PAUSED_HUMAN} and run.current_step:
            pending_steps = self._compute_downstream_pending_steps(self.get_workflow(run.workflow_name), run.current_step)
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

    def _compute_downstream_pending_steps(self, workflow: Workflow, current_step_id: str) -> List[str]:
        pending: List[str] = []
        visited: Set[str] = {current_step_id}
        queue: List[str] = []
        current = workflow.steps.get(current_step_id)
        if current:
            if getattr(current, "next", None) and current.next in workflow.steps:
                queue.append(current.next)
            transitions = getattr(current, "transitions", None)
            if transitions:
                for target in transitions.values():
                    if target in workflow.steps and target not in queue:
                        queue.append(target)

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            pending.append(node)
            step = workflow.steps.get(node)
            if not step:
                continue
            next_step = getattr(step, "next", None)
            if next_step and next_step in workflow.steps and next_step not in visited:
                queue.append(next_step)
            transitions = getattr(step, "transitions", None)
            if transitions:
                for target in transitions.values():
                    if target in workflow.steps and target not in visited and target not in queue:
                        queue.append(target)
        return pending

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        return self._store.get_run(run_id)

    def get_step_history(self, run_id: str) -> List[StepHistoryRecord]:
        return self._store.get_step_history(run_id)

    def get_active_run_for_workspace(self, workspace_path: Optional[Union[str, Path]] = None) -> Optional[RunRecord]:
        return self._store.get_active_run_for_workspace(workspace_path)

    def list_runs(
        self,
        workspace_path: Optional[Union[str, Path]] = None,
        status: Optional[Union[RunStatus, str]] = None,
        limit: int = 50,
    ) -> List[RunRecord]:
        return self._store.list_runs(workspace_path=workspace_path, status=status, limit=limit)


WorkflowEngine = WorkflowRuntime
