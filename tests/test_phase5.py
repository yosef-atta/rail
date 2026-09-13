"""Phase 5 coverage for CLI setup, defaults, and terminal workflow outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest

from rail.cli import RAIL_BLOCK_END, RAIL_BLOCK_START, main
from rail.core.loader import load_raw_workflow
from rail.core.models import Workflow
from rail.core.validator import validate_workflow
from rail.runtime.engine import WorkflowRuntime
from rail.storage.models import RunStatus
from rail.storage.store import StateStore


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOWS = (
    "default-agent.yml",
    "default-agent-github.yml",
    "default-human.yml",
)


@pytest.mark.parametrize("filename", DEFAULT_WORKFLOWS)
def test_official_default_workflows_validate(filename: str):
    raw = load_raw_workflow(REPO_ROOT / "workflows" / filename)
    result = validate_workflow(raw)
    assert result.is_valid is True, [str(error) for error in result.errors]


def test_only_three_official_default_workflows_are_bundled():
    bundled = sorted(path.name for path in (REPO_ROOT / "workflows").glob("*.y*ml"))
    assert bundled == sorted(DEFAULT_WORKFLOWS)


def test_invalid_end_status_is_rejected():
    data = {
        "version": "0.1",
        "name": "invalid-terminal",
        "start": "done",
        "steps": {"done": {"type": "end", "status": "successful-ish"}},
    }
    result = validate_workflow(data)
    assert result.is_valid is False
    assert any(error.rule == "invalid_end_status" for error in result.errors)


def test_end_status_defaults_to_completed():
    workflow = Workflow.model_validate(
        {
            "version": "0.1",
            "name": "completed-terminal",
            "start": "done",
            "steps": {"done": {"type": "end"}},
        }
    )
    with StateStore(db_path=":memory:") as store:
        runtime = WorkflowRuntime(store=store)
        step = runtime.start_run(workflow, "finish immediately")
        assert step.status == RunStatus.COMPLETED
        assert store.get_run(step.run_id).status == RunStatus.COMPLETED


def test_stopped_end_sets_stopped_run_status():
    workflow = Workflow.model_validate(
        {
            "version": "0.1",
            "name": "stoppable",
            "start": "review",
            "steps": {
                "review": {
                    "type": "agent",
                    "role": "main",
                    "prompt": "Review the work.",
                    "result": {"type": "choice", "options": ["approved", "rejected"]},
                    "transitions": {"approved": "done", "rejected": "stopped"},
                },
                "stopped": {"type": "end", "status": "stopped"},
                "done": {"type": "end"},
            },
        }
    )
    with StateStore(db_path=":memory:") as store:
        runtime = WorkflowRuntime(store=store)
        step = runtime.start_run(workflow, "test rejection")
        result = runtime.complete_step(step.run_id, result="rejected")
        assert result.status == RunStatus.STOPPED
        assert result.step_info.is_terminal is True
        assert store.get_run(step.run_id).status == RunStatus.STOPPED


def test_init_creates_managed_blocks_and_is_idempotent(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Existing instructions\n", encoding="utf-8")

    assert main(["init", "--workspace", str(tmp_path)]) == 0
    first_agents = agents.read_text(encoding="utf-8")
    first_claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    assert "# Existing instructions" in first_agents
    assert first_agents.count(RAIL_BLOCK_START) == 1
    assert first_agents.count(RAIL_BLOCK_END) == 1
    assert first_claude.count(RAIL_BLOCK_START) == 1
    assert first_claude.count(RAIL_BLOCK_END) == 1

    assert main(["init", "--workspace", str(tmp_path)]) == 0
    assert agents.read_text(encoding="utf-8") == first_agents
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == first_claude


def test_init_updates_only_existing_managed_block(tmp_path: Path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "before\n\n<!-- RAIL:START -->\nold managed content\n<!-- RAIL:END -->\n\nafter\n",
        encoding="utf-8",
    )
    assert main(["init", "--workspace", str(tmp_path)]) == 0
    content = agents.read_text(encoding="utf-8")
    assert content.startswith("before")
    assert content.rstrip().endswith("after")
    assert "old managed content" not in content
    assert content.count(RAIL_BLOCK_START) == 1


def test_workflows_lists_global_workflows(monkeypatch, tmp_path: Path, capsys):
    workflows_dir = tmp_path / ".rail" / "workflows"
    workflows_dir.mkdir(parents=True)
    for filename in DEFAULT_WORKFLOWS:
        source = REPO_ROOT / "workflows" / filename
        (workflows_dir / filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr("rail.core.loader.get_default_workflows_dir", lambda: workflows_dir)
    assert main(["workflows"]) == 0
    output = capsys.readouterr().out
    assert "default-agent" in output
    assert "default-agent-github" in output
    assert "default-human" in output


def test_status_reports_no_active_run(tmp_path: Path, capsys):
    db_path = tmp_path / "rail.db"
    assert main(["status", "--workspace", str(tmp_path), "--db-path", str(db_path)]) == 0
    assert "No active Rail workflow" in capsys.readouterr().out


def test_status_reports_active_run(tmp_path: Path, capsys):
    db_path = tmp_path / "rail.db"
    with StateStore(db_path=db_path) as store:
        run = store.create_run(
            workflow_name="default-human",
            task="Implement feature",
            current_step="plan",
            workspace_path=tmp_path,
        )

    assert main(["status", "--workspace", str(tmp_path), "--db-path", str(db_path)]) == 0
    output = capsys.readouterr().out
    assert run.run_id in output
    assert "Workflow: default-human" in output
    assert "Status: running" in output
    assert "Current step: plan" in output


def test_setup_script_seeds_only_official_defaults():
    content = (REPO_ROOT / "setup.ps1").read_text(encoding="utf-8")
    for filename in DEFAULT_WORKFLOWS:
        assert f'"{filename}"' in content
    assert "careful-feature.yaml" not in content
    assert '"default.yaml"' not in content
    assert "rail workflows" in content


def test_setup_script_supports_remote_execution():
    content = (REPO_ROOT / "setup.ps1").read_text(encoding="utf-8")
    assert "$scriptPath = $MyInvocation.MyCommand.Path" in content
    assert "if ($scriptPath -and (Test-Path -LiteralPath $scriptPath))" in content
    assert "raw.githubusercontent.com/$repoOwner/$repoName/$repoBranch" in content
    assert 'Invoke-WebRequest -UseBasicParsing -Uri $workflowUrl -OutFile $destinationPath' in content
    assert 'git+https://github.com/$repoOwner/$repoName.git' in content
