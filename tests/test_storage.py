"""Unit and integration tests for Rail's SQLite persistence layer and state store."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest

from rail.core.exceptions import RailRunNotFoundError
from rail.storage import (
    ACTIVE_RUN_STATUSES,
    RunRecord,
    RunStatus,
    StateStore,
    StepHistoryRecord,
    connect_db,
    get_default_db_path,
    init_db,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Return a path to a temporary database file."""
    return tmp_path / "test_rail.db"


@pytest.fixture
def store(temp_db_path: Path) -> StateStore:
    """Return an initialized StateStore using a temporary database."""
    with StateStore(temp_db_path) as s:
        yield s


# -----------------------------------------------------------------------------
# 1. Database Initialization & Migration Tests
# -----------------------------------------------------------------------------


def test_get_default_db_path() -> None:
    """Verify default database path points to ~/.rail/rail.db."""
    default_path = get_default_db_path()
    assert default_path == Path.home() / ".rail" / "rail.db"


def test_init_db_creates_tables_and_indexes(temp_db_path: Path) -> None:
    """Verify database initialization creates schema tables, indexes, and migrations."""
    conn = init_db(temp_db_path)
    try:
        # Check tables
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {row["name"] for row in cur.fetchall()}
        assert "runs" in tables
        assert "step_history" in tables
        assert "schema_migrations" in tables

        # Check migration version
        mig_cur = conn.execute("SELECT MAX(version) AS ver FROM schema_migrations;")
        assert mig_cur.fetchone()["ver"] == 1

        # Check indexes
        idx_cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%';"
        )
        indexes = {row["name"] for row in idx_cur.fetchall()}
        assert "idx_runs_workspace_status" in indexes
        assert "idx_runs_status" in indexes
        assert "idx_step_history_run_id" in indexes
    finally:
        conn.close()


def test_init_db_is_idempotent(temp_db_path: Path) -> None:
    """Verify calling init_db multiple times does not error or duplicate schema."""
    conn1 = init_db(temp_db_path)
    conn1.close()

    conn2 = init_db(temp_db_path)
    try:
        mig_cur = conn2.execute("SELECT COUNT(*) AS count FROM schema_migrations;")
        assert mig_cur.fetchone()["count"] == 1
    finally:
        conn2.close()


def test_connect_db_default_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify connect_db uses get_default_db_path() when db_path is None."""
    mock_db = tmp_path / "mock_rail" / "rail.db"
    monkeypatch.setattr("rail.storage.db.get_default_db_path", lambda: mock_db)
    conn = connect_db(None)
    try:
        assert mock_db.exists()
    finally:
        conn.close()


def test_connect_db_creates_parent_dir(tmp_path: Path) -> None:
    """Verify connect_db creates missing nested parent directories."""
    nested_path = tmp_path / "deep" / "nested" / "dir" / "rail.db"
    assert not nested_path.parent.exists()
    conn = connect_db(nested_path)
    try:
        assert nested_path.parent.exists()
    finally:
        conn.close()


def test_conn_property_reconnects_when_none(temp_db_path: Path) -> None:
    """Verify accessing conn property re-initializes connection if previously closed."""
    store = StateStore(temp_db_path)
    store.close()
    assert store._conn is None
    # Accessing conn should automatically re-open connection
    assert store.conn is not None
    store.close()



def test_in_memory_db() -> None:
    """Verify StateStore supports in-memory database (:memory:)."""
    with StateStore(":memory:") as mem_store:
        run = mem_store.create_run(workflow_name="default", task="In-memory test")
        assert run.run_id == "R-000001"
        assert mem_store.get_run("R-000001") is not None


# -----------------------------------------------------------------------------
# 2. Run Creation & Sequential Identifiers
# -----------------------------------------------------------------------------


def test_create_run_sequential_ids(store: StateStore) -> None:
    """Verify sequential run_id generation (R-000001, R-000002, etc.)."""
    run1 = store.create_run(workflow_name="default", task="First task", current_step="plan")
    assert run1.run_id == "R-000001"
    assert run1.workflow_name == "default"
    assert run1.task == "First task"
    assert run1.current_step == "plan"
    assert run1.status == RunStatus.RUNNING
    assert run1.is_active is True

    run2 = store.create_run(workflow_name="careful-feature", task="Second task", current_step="plan")
    assert run2.run_id == "R-000002"

    run3 = store.create_run(workflow_name="fast-fix", task="Third task")
    assert run3.run_id == "R-000003"


def test_create_run_custom_id(store: StateStore) -> None:
    """Verify creating a run with an explicit custom run_id."""
    run = store.create_run(
        workflow_name="default",
        task="Custom ID task",
        run_id="CUSTOM-123",
    )
    assert run.run_id == "CUSTOM-123"

    fetched = store.get_run("CUSTOM-123")
    assert fetched is not None
    assert fetched.run_id == "CUSTOM-123"


def test_create_run_validation_empty_fields(store: StateStore) -> None:
    """Verify validation rejects empty workflow_name or task."""
    with pytest.raises(ValueError, match="workflow_name cannot be empty"):
        store.create_run(workflow_name="  ", task="valid task")

    with pytest.raises(ValueError, match="task cannot be empty"):
        store.create_run(workflow_name="default", task="   ")


def test_create_run_workspace_defaults(store: StateStore) -> None:
    """Verify workspace_path defaults to current working directory resolved."""
    run = store.create_run(workflow_name="default", task="CWD workspace run")
    assert run.workspace_path == str(Path.cwd().resolve())


def test_create_run_explicit_workspace(store: StateStore, tmp_path: Path) -> None:
    """Verify explicit workspace path normalization."""
    ws = tmp_path / "custom_project"
    run = store.create_run(
        workflow_name="default",
        task="Explicit workspace",
        workspace_path=ws,
    )
    assert run.workspace_path == str(ws.resolve())


# -----------------------------------------------------------------------------
# 3. State Updates & Lookups
# -----------------------------------------------------------------------------


def test_get_run_nonexistent(store: StateStore) -> None:
    """Verify get_run returns None for nonexistent run_id."""
    assert store.get_run("R-999999") is None


def test_update_run_step_advancement(store: StateStore) -> None:
    """Verify update_run_step modifies current_step and status."""
    run = store.create_run(workflow_name="default", task="Advancing step", current_step="plan")
    initial_updated_at = run.updated_at

    updated = store.update_run_step(
        run_id=run.run_id,
        current_step="review_plan",
        status=RunStatus.RUNNING,
    )
    assert updated.current_step == "review_plan"
    assert updated.status == RunStatus.RUNNING
    assert updated.updated_at >= initial_updated_at


def test_update_run_step_paused_human(store: StateStore) -> None:
    """Verify pausing a run at a human gate."""
    run = store.create_run(workflow_name="default", task="Human step test", current_step="verify")
    updated = store.update_run_step(
        run_id=run.run_id,
        current_step="human_review",
        status=RunStatus.PAUSED_HUMAN,
    )
    assert updated.current_step == "human_review"
    assert updated.status == RunStatus.PAUSED_HUMAN
    assert updated.is_active is True


def test_update_run_step_not_found(store: StateStore) -> None:
    """Verify update_run_step raises RailRunNotFoundError for missing run."""
    with pytest.raises(RailRunNotFoundError, match="R-NONEXISTENT"):
        store.update_run_step("R-NONEXISTENT", current_step="step1")


def test_update_run_status(store: StateStore) -> None:
    """Verify updating run status directly."""
    run = store.create_run(workflow_name="default", task="Completion test")
    completed = store.update_run_status(run.run_id, RunStatus.COMPLETED)
    assert completed.status == RunStatus.COMPLETED
    assert completed.is_active is False

    failed_run = store.create_run(workflow_name="default", task="Failure test")
    failed = store.update_run_status(failed_run.run_id, "failed")
    assert failed.status == RunStatus.FAILED
    assert failed.is_active is False


def test_update_run_status_not_found(store: StateStore) -> None:
    """Verify update_run_status raises RailRunNotFoundError for missing run."""
    with pytest.raises(RailRunNotFoundError):
        store.update_run_status("R-MISSING", RunStatus.COMPLETED)


# -----------------------------------------------------------------------------
# 4. Step History & Choice Outcomes
# -----------------------------------------------------------------------------


def test_record_step_completion(store: StateStore) -> None:
    """Verify recording agent step completions in step_history."""
    run = store.create_run(workflow_name="default", task="History test", current_step="plan")

    history1 = store.record_step_completion(
        run_id=run.run_id,
        step_id="plan",
        step_type="agent",
        role="main",
        result=None,
        transition_taken="review_plan",
    )
    assert history1.id == 1
    assert history1.run_id == run.run_id
    assert history1.step_id == "plan"
    assert history1.step_type == "agent"
    assert history1.role == "main"
    assert history1.result is None
    assert history1.transition_taken == "review_plan"
    assert history1.started_at is not None
    assert history1.completed_at is not None

    # Record choice result
    history2 = store.record_step_completion(
        run_id=run.run_id,
        step_id="review_plan",
        step_type="agent",
        role="subagent",
        result="approved",
        transition_taken="implement",
    )
    assert history2.id == 2
    assert history2.step_id == "review_plan"
    assert history2.role == "subagent"
    assert history2.result == "approved"
    assert history2.transition_taken == "implement"

    all_history = store.get_step_history(run.run_id)
    assert len(all_history) == 2
    assert all_history[0].step_id == "plan"
    assert all_history[1].step_id == "review_plan"


def test_record_step_completion_custom_timestamps(store: StateStore) -> None:
    """Verify passing explicit datetime objects and string timestamps."""
    run = store.create_run(workflow_name="default", task="Timestamp test")
    t_start = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 9, 12, 10, 5, 0, tzinfo=timezone.utc)

    entry = store.record_step_completion(
        run_id=run.run_id,
        step_id="plan",
        step_type="agent",
        role="main",
        started_at=t_start,
        completed_at=t_end,
    )
    assert entry.started_at == t_start.isoformat()
    assert entry.completed_at == t_end.isoformat()

    # Naive datetime
    naive_start = datetime(2026, 9, 12, 10, 6, 0)
    # String timestamp
    str_end = "2026-09-12T10:10:00+00:00"
    entry2 = store.record_step_completion(
        run_id=run.run_id,
        step_id="review_plan",
        step_type="agent",
        role="subagent",
        started_at=naive_start,
        completed_at=str_end,
    )
    assert "+00:00" in entry2.started_at
    assert entry2.completed_at == str_end



def test_record_step_completion_missing_run(store: StateStore) -> None:
    """Verify record_step_completion raises RailRunNotFoundError if run does not exist."""
    with pytest.raises(RailRunNotFoundError):
        store.record_step_completion(
            run_id="R-MISSING",
            step_id="plan",
            step_type="agent",
        )


# -----------------------------------------------------------------------------
# 5. Human Gate Action & Atomic Unpausing
# -----------------------------------------------------------------------------


def test_record_human_action_atomic(store: StateStore) -> None:
    """Verify recording human action writes history and advances/unpauses the run atomically."""
    run = store.create_run(
        workflow_name="default",
        task="Human gate test",
        current_step="human_review",
    )
    # Pause run for human gate
    store.update_run_step(run.run_id, current_step="human_review", status=RunStatus.PAUSED_HUMAN)

    # Human approves and transitions to done
    updated_run = store.record_human_action(
        run_id=run.run_id,
        step_id="human_review",
        action="approve",
        next_step="done",
    )

    # Verify run updated and unpaused
    assert updated_run.current_step == "done"
    assert updated_run.status == RunStatus.RUNNING
    assert updated_run.is_active is True

    # Verify history recorded
    history = store.get_step_history(run.run_id)
    assert len(history) == 1
    assert history[0].step_id == "human_review"
    assert history[0].step_type == "human"
    assert history[0].result == "approve"
    assert history[0].transition_taken == "done"


def test_record_human_action_missing_run(store: StateStore) -> None:
    """Verify record_human_action raises RailRunNotFoundError for missing run."""
    with pytest.raises(RailRunNotFoundError):
        store.record_human_action("R-NONEXISTENT", step_id="gate", action="approve")


# -----------------------------------------------------------------------------
# 6. Workspace-Scoped Active Run Queries
# -----------------------------------------------------------------------------


def test_get_active_run_for_workspace(store: StateStore, tmp_path: Path) -> None:
    """Verify get_active_run_for_workspace correctly identifies active run for a project."""
    ws_a = tmp_path / "project_a"
    ws_b = tmp_path / "project_b"

    # Workspace A: Run 1 completed
    run_a1 = store.create_run(workflow_name="default", task="A1", workspace_path=ws_a)
    store.update_run_status(run_a1.run_id, RunStatus.COMPLETED)

    # Workspace A: Run 2 running
    run_a2 = store.create_run(workflow_name="default", task="A2", workspace_path=ws_a)

    # Workspace B: Run 3 paused for human
    run_b = store.create_run(workflow_name="default", task="B", workspace_path=ws_b)
    store.update_run_step(run_b.run_id, current_step="review", status=RunStatus.PAUSED_HUMAN)

    # Workspace A should find run_a2
    active_a = store.get_active_run_for_workspace(ws_a)
    assert active_a is not None
    assert active_a.run_id == run_a2.run_id

    # Workspace B should find run_b
    active_b = store.get_active_run_for_workspace(ws_b)
    assert active_b is not None
    assert active_b.run_id == run_b.run_id

    # Complete Workspace A's run
    store.update_run_status(run_a2.run_id, RunStatus.COMPLETED)
    assert store.get_active_run_for_workspace(ws_a) is None


def test_list_runs_filtering(store: StateStore, tmp_path: Path) -> None:
    """Verify list_runs supports filtering by workspace and status."""
    ws = tmp_path / "proj"
    r1 = store.create_run("w1", "t1", workspace_path=ws)
    r2 = store.create_run("w2", "t2", workspace_path=ws)
    store.update_run_status(r1.run_id, RunStatus.COMPLETED)

    all_runs = store.list_runs(workspace_path=ws)
    assert len(all_runs) == 2

    completed_runs = store.list_runs(workspace_path=ws, status=RunStatus.COMPLETED)
    assert len(completed_runs) == 1
    assert completed_runs[0].run_id == r1.run_id

    running_runs = store.list_runs(workspace_path=ws, status=RunStatus.RUNNING)
    assert len(running_runs) == 1
    assert running_runs[0].run_id == r2.run_id


# -----------------------------------------------------------------------------
# 7. Acceptance Gate: Process Crash & State Recovery Verification
# -----------------------------------------------------------------------------


def test_process_termination_and_exact_state_recovery(temp_db_path: Path, tmp_path: Path) -> None:
    """Acceptance Gate: Simulate sudden process termination and verify exact state recovery."""
    workspace = tmp_path / "my_project"

    # --- Process 1: Start workflow and make progress ---
    store1 = StateStore(temp_db_path)
    run = store1.create_run(
        workflow_name="careful-feature",
        task="Implement user authentication with JWT",
        current_step="plan",
        workspace_path=workspace,
    )
    run_id = run.run_id
    assert run_id == "R-000001"

    # Step 1: plan completed
    store1.record_step_completion(
        run_id=run_id,
        step_id="plan",
        step_type="agent",
        role="main",
        result=None,
        transition_taken="review_plan",
    )
    store1.update_run_step(run_id, current_step="review_plan")

    # Step 2: review_plan completed with changes_required (first loop)
    store1.record_step_completion(
        run_id=run_id,
        step_id="review_plan",
        step_type="agent",
        role="subagent",
        result="changes_required",
        transition_taken="plan",
    )
    store1.update_run_step(run_id, current_step="plan")

    # Step 3: plan revised
    store1.record_step_completion(
        run_id=run_id,
        step_id="plan",
        step_type="agent",
        role="main",
        result=None,
        transition_taken="review_plan",
    )
    store1.update_run_step(run_id, current_step="review_plan")

    # Step 4: review_plan completed with approved
    store1.record_step_completion(
        run_id=run_id,
        step_id="review_plan",
        step_type="agent",
        role="subagent",
        result="approved",
        transition_taken="implement",
    )
    store1.update_run_step(run_id, current_step="implement")

    # Step 5: implement completed
    store1.record_step_completion(
        run_id=run_id,
        step_id="implement",
        step_type="agent",
        role="main",
        result=None,
        transition_taken="verify",
    )
    store1.update_run_step(run_id, current_step="verify")

    # Step 6: verify completed, reaches human_review gate
    store1.record_step_completion(
        run_id=run_id,
        step_id="verify",
        step_type="agent",
        role="main",
        result=None,
        transition_taken="human_review",
    )
    pre_crash_run = store1.update_run_step(
        run_id,
        current_step="human_review",
        status=RunStatus.PAUSED_HUMAN,
    )
    pre_crash_history = store1.get_step_history(run_id)

    # --- SUDDEN PROCESS TERMINATION ---
    # Abruptly close connection and discard store1 instance to simulate process crash
    store1.close()
    del store1

    # --- Process 2: Brand new process / connection launched after reboot ---
    store2 = StateStore(temp_db_path)

    # 1. Recover active run for workspace
    recovered_active = store2.get_active_run_for_workspace(workspace)
    assert recovered_active is not None
    assert recovered_active.run_id == run_id
    assert recovered_active.workflow_name == "careful-feature"
    assert recovered_active.task == "Implement user authentication with JWT"
    assert recovered_active.current_step == "human_review"
    assert recovered_active.status == RunStatus.PAUSED_HUMAN
    assert recovered_active.is_active is True
    assert recovered_active.created_at == pre_crash_run.created_at
    assert recovered_active.updated_at == pre_crash_run.updated_at

    # 2. Recover exact step history
    recovered_history = store2.get_step_history(run_id)
    assert len(recovered_history) == len(pre_crash_history) == 6

    for orig, rec in zip(pre_crash_history, recovered_history):
        assert orig.id == rec.id
        assert orig.step_id == rec.step_id
        assert orig.step_type == rec.step_type
        assert orig.role == rec.role
        assert orig.result == rec.result
        assert orig.transition_taken == rec.transition_taken
        assert orig.started_at == rec.started_at
        assert orig.completed_at == rec.completed_at

    # 3. Resume workflow from restored state: resolve human gate in Process 2
    resumed_run = store2.record_human_action(
        run_id=run_id,
        step_id="human_review",
        action="approve",
        next_step="done",
    )
    assert resumed_run.current_step == "done"
    assert resumed_run.status == RunStatus.RUNNING

    # Mark done/completed
    final_run = store2.update_run_status(run_id, RunStatus.COMPLETED)
    assert final_run.status == RunStatus.COMPLETED
    assert final_run.is_active is False

    # Verify no active run remains for the workspace
    assert store2.get_active_run_for_workspace(workspace) is None

    # Step history now contains all 7 steps
    final_history = store2.get_step_history(run_id)
    assert len(final_history) == 7
    assert final_history[-1].step_id == "human_review"
    assert final_history[-1].result == "approve"
    assert final_history[-1].transition_taken == "done"

    store2.close()


# -----------------------------------------------------------------------------
# 8. Foreign Key Constraints & Cascading Deletion
# -----------------------------------------------------------------------------


def test_foreign_key_enforcement(store: StateStore) -> None:
    """Verify foreign key constraints prevent inserting step_history without valid run."""
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO step_history (
                run_id, step_id, step_type, role, result, transition_taken, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                "NON-EXISTENT-RUN",
                "plan",
                "agent",
                "main",
                None,
                "implement",
                "2026-09-12T00:00:00Z",
                "2026-09-12T00:01:00Z",
            ),
        )


def test_delete_run_cascades_to_step_history(store: StateStore) -> None:
    """Verify deleting a run cascades and removes all associated step history."""
    run = store.create_run(workflow_name="default", task="To be deleted")
    store.record_step_completion(run.run_id, "step1", "agent")
    store.record_step_completion(run.run_id, "step2", "agent")

    assert len(store.get_step_history(run.run_id)) == 2

    assert store.delete_run(run.run_id) is True
    assert store.get_run(run.run_id) is None
    assert len(store.get_step_history(run.run_id)) == 0
