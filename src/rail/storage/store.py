"""Repository state store for durable workflow execution tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import List, Optional, Union

from rail.core.exceptions import RailRunNotFoundError
from rail.storage.db import init_db
from rail.storage.models import ACTIVE_RUN_STATUSES, RunRecord, RunStatus, StepHistoryRecord


def _now_utc_iso() -> str:
    """Return current UTC time formatted as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _format_timestamp(ts: Optional[Union[datetime, str]]) -> str:
    """Format an optional datetime or string as an ISO 8601 string, defaulting to now."""
    if ts is None:
        return _now_utc_iso()
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    return str(ts)


def _resolve_workspace_path(workspace_path: Optional[Union[str, Path]]) -> str:
    """Resolve and normalize workspace path, defaulting to cwd."""
    if workspace_path is None:
        return str(Path.cwd().resolve())
    return str(Path(workspace_path).resolve())


class StateStore:
    """Durable state store for workflow runs, steps, and transitions."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_connection()

    def _init_connection(self) -> None:
        """Initialize connection and execute database migrations."""
        self._conn = init_db(self.db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the active SQLite connection, re-opening if closed."""
        if self._conn is None:
            self._init_connection()
        return self._conn

    def close(self) -> None:
        """Close the active database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _generate_next_run_id(self) -> str:
        """Generate next monotonic run identifier (e.g. R-000001)."""
        cur = self.conn.execute(
            """
            SELECT coalesce(MAX(CAST(substr(run_id, 3) AS INTEGER)), 0) AS max_id
            FROM runs
            WHERE run_id LIKE 'R-%';
            """
        )
        row = cur.fetchone()
        next_id = (row["max_id"] if row else 0) + 1
        return f"R-{next_id:06d}"

    def create_run(
        self,
        workflow_name: str,
        task: str,
        current_step: Optional[str] = None,
        workspace_path: Optional[Union[str, Path]] = None,
        run_id: Optional[str] = None,
    ) -> RunRecord:
        """Create and persist a new workflow run.

        If run_id is omitted, generates the next sequential identifier (e.g. R-000001).
        """
        if not workflow_name or not workflow_name.strip():
            raise ValueError("workflow_name cannot be empty")
        if not task or not task.strip():
            raise ValueError("task cannot be empty")

        resolved_workspace = _resolve_workspace_path(workspace_path)
        now_iso = _now_utc_iso()

        with self.conn:
            assigned_run_id = run_id if run_id else self._generate_next_run_id()
            status = RunStatus.RUNNING.value

            self.conn.execute(
                """
                INSERT INTO runs (
                    run_id, workflow_name, task, status, current_step,
                    workspace_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    assigned_run_id,
                    workflow_name.strip(),
                    task.strip(),
                    status,
                    current_step,
                    resolved_workspace,
                    now_iso,
                    now_iso,
                ),
            )

        return self.get_run(assigned_run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Retrieve a workflow run by its run_id."""
        cur = self.conn.execute("SELECT * FROM runs WHERE run_id = ?;", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        return RunRecord.model_validate(dict(row))

    def update_run_step(
        self,
        run_id: str,
        current_step: Optional[str],
        status: Optional[Union[RunStatus, str]] = None,
    ) -> RunRecord:
        """Update active step and optional status of a workflow run.

        Raises RailRunNotFoundError if the run does not exist.
        """
        now_iso = _now_utc_iso()

        with self.conn:
            existing = self.get_run(run_id)
            if not existing:
                raise RailRunNotFoundError(run_id)

            new_status = (
                status.value if isinstance(status, RunStatus) else (status or existing.status.value)
            )

            self.conn.execute(
                """
                UPDATE runs
                SET current_step = ?, status = ?, updated_at = ?
                WHERE run_id = ?;
                """,
                (current_step, new_status, now_iso, run_id),
            )

        return self.get_run(run_id)  # type: ignore[return-value]

    def update_run_status(
        self,
        run_id: str,
        status: Union[RunStatus, str],
    ) -> RunRecord:
        """Update lifecycle status of a workflow run."""
        status_val = status.value if isinstance(status, RunStatus) else str(status)
        now_iso = _now_utc_iso()

        with self.conn:
            existing = self.get_run(run_id)
            if not existing:
                raise RailRunNotFoundError(run_id)

            self.conn.execute(
                """
                UPDATE runs
                SET status = ?, updated_at = ?
                WHERE run_id = ?;
                """,
                (status_val, now_iso, run_id),
            )

        return self.get_run(run_id)  # type: ignore[return-value]

    def record_step_completion(
        self,
        run_id: str,
        step_id: str,
        step_type: str,
        role: Optional[str] = None,
        result: Optional[str] = None,
        transition_taken: Optional[str] = None,
        started_at: Optional[Union[datetime, str]] = None,
        completed_at: Optional[Union[datetime, str]] = None,
    ) -> StepHistoryRecord:
        """Record the completion of a step execution in step_history."""
        start_ts = _format_timestamp(started_at)
        comp_ts = _format_timestamp(completed_at)

        with self.conn:
            existing = self.get_run(run_id)
            if not existing:
                raise RailRunNotFoundError(run_id)

            cur = self.conn.execute(
                """
                INSERT INTO step_history (
                    run_id, step_id, step_type, role, result,
                    transition_taken, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    run_id,
                    step_id,
                    step_type,
                    role,
                    result,
                    transition_taken,
                    start_ts,
                    comp_ts,
                ),
            )
            history_id = cur.lastrowid
            self.conn.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?;",
                (comp_ts, run_id),
            )

        hist_cur = self.conn.execute(
            "SELECT * FROM step_history WHERE id = ?;",
            (history_id,),
        )
        row = hist_cur.fetchone()
        return StepHistoryRecord.model_validate(dict(row))

    def record_human_action(
        self,
        run_id: str,
        step_id: str,
        action: str,
        next_step: Optional[str] = None,
        role: Optional[str] = None,
        started_at: Optional[Union[datetime, str]] = None,
        completed_at: Optional[Union[datetime, str]] = None,
    ) -> RunRecord:
        """Record human gate action and advance workflow run atomically.

        Inserts human step completion into step_history and updates the run's
        current_step and status (unpausing to RUNNING if next_step is set).
        """
        start_ts = _format_timestamp(started_at)
        comp_ts = _format_timestamp(completed_at)

        with self.conn:
            existing = self.get_run(run_id)
            if not existing:
                raise RailRunNotFoundError(run_id)

            # 1. Record in step_history
            self.conn.execute(
                """
                INSERT INTO step_history (
                    run_id, step_id, step_type, role, result,
                    transition_taken, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    run_id,
                    step_id,
                    "human",
                    role,
                    action,
                    next_step,
                    start_ts,
                    comp_ts,
                ),
            )

            # 2. Update run current_step and unpause if advancing
            target_status = RunStatus.RUNNING.value if next_step else existing.status.value
            self.conn.execute(
                """
                UPDATE runs
                SET current_step = ?, status = ?, updated_at = ?
                WHERE run_id = ?;
                """,
                (next_step if next_step else existing.current_step, target_status, comp_ts, run_id),
            )

        return self.get_run(run_id)  # type: ignore[return-value]

    def get_step_history(self, run_id: str) -> List[StepHistoryRecord]:
        """Retrieve all recorded step executions for a run in chronological order."""
        cur = self.conn.execute(
            "SELECT * FROM step_history WHERE run_id = ? ORDER BY id ASC;",
            (run_id,),
        )
        return [StepHistoryRecord.model_validate(dict(row)) for row in cur.fetchall()]

    def get_active_run_for_workspace(
        self,
        workspace_path: Optional[Union[str, Path]] = None,
    ) -> Optional[RunRecord]:
        """Find the active (running or paused_human) run for a workspace.

        Returns the most recently created active run, or None if no run is active.
        """
        resolved_workspace = _resolve_workspace_path(workspace_path)
        cur = self.conn.execute(
            """
            SELECT * FROM runs
            WHERE workspace_path = ? AND status IN (?, ?)
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1;
            """,
            (resolved_workspace, ACTIVE_RUN_STATUSES[0], ACTIVE_RUN_STATUSES[1]),
        )
        row = cur.fetchone()
        if not row:
            return None
        return RunRecord.model_validate(dict(row))

    def list_runs(
        self,
        workspace_path: Optional[Union[str, Path]] = None,
        status: Optional[Union[RunStatus, str]] = None,
        limit: int = 50,
    ) -> List[RunRecord]:
        """List workflow runs, optionally filtered by workspace and status."""
        query = "SELECT * FROM runs WHERE 1=1"
        params: List[Union[str, int]] = []

        if workspace_path is not None:
            query += " AND workspace_path = ?"
            params.append(_resolve_workspace_path(workspace_path))

        if status is not None:
            query += " AND status = ?"
            status_val = status.value if isinstance(status, RunStatus) else str(status)
            params.append(status_val)

        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?;"
        params.append(limit)

        cur = self.conn.execute(query, params)
        return [RunRecord.model_validate(dict(row)) for row in cur.fetchall()]

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and its associated step history (via CASCADE)."""
        with self.conn:
            cur = self.conn.execute("DELETE FROM runs WHERE run_id = ?;", (run_id,))
            return cur.rowcount > 0
