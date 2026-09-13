"""Contract tests for Rail's three official default workflows."""

from pathlib import Path

from rail.core.loader import load_raw_workflow


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / "workflows"


def _load(name: str) -> dict:
    return load_raw_workflow(WORKFLOWS_DIR / f"{name}.yml")


def test_default_agent_contract():
    workflow = _load("default-agent")
    steps = workflow["steps"]

    assert workflow["start"] == "plan"
    assert steps["plan"]["role"] == "subagent"
    assert steps["plan"]["name"] == "planner"
    assert steps["review_plan"]["name"] == "plan-reviewer"
    assert steps["review_plan"]["transitions"] == {"approved": "code", "rejected": "stopped"}
    assert steps["code"]["name"] == "code"
    assert steps["verify"]["name"] == "verifier"
    assert steps["verify"]["transitions"] == {"approved": "review", "rejected": "stopped"}
    assert steps["review"]["name"] == "reviewer"
    assert steps["review"]["transitions"] == {"approved": "report", "rejected": "stopped"}
    assert steps["report"]["name"] == "reporter"
    assert "Commit the completed implementation" in steps["report"]["prompt"]
    assert steps["stopped"] == {"type": "end", "status": "stopped"}
    assert steps["done"] == {"type": "end"}


def test_default_agent_github_contract():
    workflow = _load("default-agent-github")
    steps = workflow["steps"]

    assert steps["plan"]["name"] == "planner"
    assert steps["review_plan"]["name"] == "plan-reviewer"
    assert steps["code"]["name"] == "code"
    assert steps["verify"]["name"] == "verifier"
    assert steps["review"]["name"] == "reviewer"
    assert steps["review"]["transitions"]["approved"] == "github"
    assert steps["github"]["name"] == "github"
    github_prompt = steps["github"]["prompt"]
    assert "normal merge commit" in github_prompt
    assert "Never use squash merge" in github_prompt
    assert "Never use rebase merge" in github_prompt
    assert "Switch to the base branch" in github_prompt
    assert "Pull the latest base branch state" in github_prompt
    assert steps["github"]["next"] == "report"
    assert steps["report"]["name"] == "reporter"


def test_default_human_contract():
    workflow = _load("default-human")
    steps = workflow["steps"]

    assert workflow["start"] == "plan"
    assert steps["plan"]["role"] == "main"
    assert steps["human_plan_review"]["type"] == "human"
    assert steps["human_plan_review"]["transitions"] == {"approve": "code", "reject": "plan"}
    assert steps["code"]["role"] == "main"
    assert steps["verify"]["transitions"] == {"approved": "review", "changes_required": "code"}
    assert steps["review"]["transitions"] == {"approved": "human_manual_review", "changes_required": "code"}
    assert steps["human_manual_review"]["transitions"] == {"approve": "finalize", "reject": "code"}
    assert steps["finalize"]["role"] == "main"
    assert "Commit the approved implementation" in steps["finalize"]["prompt"]
    assert steps["finalize"]["next"] == "done"
