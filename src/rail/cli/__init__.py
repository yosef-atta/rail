"""Rail command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, TextIO

from rail.core.exceptions import RailWorkflowNotFoundError, RailWorkflowParseError
from rail.core.loader import find_workflow_file, list_workflow_files, load_raw_workflow
from rail.core.validator import validate_workflow
from rail.storage.store import StateStore

RAIL_BLOCK_START = "<!-- RAIL:START -->"
RAIL_BLOCK_END = "<!-- RAIL:END -->"
RAIL_MANAGED_BLOCK = """<!-- RAIL:START -->

## Rail Workflow Execution

This project supports externally controlled coding workflows through Rail.

When the user explicitly requests a task using a Rail workflow, you MUST:

1. Start the requested workflow before planning, editing files, or implementing the task.
2. Follow only the current workflow step returned by Rail.
3. Never skip, reorder, invent, or infer workflow steps.
4. Never transition to another workflow step yourself.
5. Report completion through Rail after completing an agent step.
6. Stop immediately when Rail reaches a human step or a terminal stopped outcome.
7. Never approve or bypass a human gate yourself.
8. Continue only after the human gate has been explicitly resolved.
9. If workflow state is unclear, query Rail before continuing.

Rail is authoritative over workflow execution.

<!-- RAIL:END -->"""


def _print_message(message: str, file: Optional[TextIO] = None) -> None:
    """Print a CLI message using the current stdout/stderr stream at call time.

    Resolving stdout lazily keeps the helper compatible with pytest capture and
    other callers that temporarily replace sys.stdout.
    """
    target = file if file is not None else sys.stdout
    try:
        print(message, file=target)
    except UnicodeEncodeError:
        safe_message = (
            message.replace("\u2713", "[OK]")
            .replace("\u2717", "[FAIL]")
            .replace("\u2192", "->")
            .replace("\u25cb", "o")
        )
        print(safe_message, file=target)


def _upsert_managed_block(path: Path) -> str:
    """Create or replace only Rail's managed block while preserving user content."""
    if path.exists():
        original = path.read_text(encoding="utf-8")
    else:
        original = ""

    start_index = original.find(RAIL_BLOCK_START)
    end_index = original.find(RAIL_BLOCK_END)

    if start_index >= 0 and end_index >= start_index:
        end_index += len(RAIL_BLOCK_END)
        updated = original[:start_index] + RAIL_MANAGED_BLOCK + original[end_index:]
        action = "updated"
    else:
        separator = "" if not original else ("\n" if original.endswith("\n") else "\n\n")
        updated = original + separator + RAIL_MANAGED_BLOCK + "\n"
        action = "created" if not original else "appended"

    if updated != original:
        path.write_text(updated, encoding="utf-8")
    return action


def cmd_init(workspace: Optional[str] = None) -> int:
    root = Path(workspace).resolve() if workspace else Path.cwd().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _print_message(f"Initializing Rail instructions in {root}")
    for filename in ("AGENTS.md", "CLAUDE.md"):
        path = root / filename
        action = _upsert_managed_block(path)
        _print_message(f"  {filename}: {action}")
    _print_message("Rail project instructions are ready.")
    return 0


def cmd_workflows() -> int:
    files = list_workflow_files()
    if not files:
        _print_message("No global Rail workflows found.")
        return 0

    _print_message("Available workflows:\n")
    for path in files:
        try:
            raw = load_raw_workflow(path)
            name = raw.get("name") if isinstance(raw.get("name"), str) else path.stem
            description = raw.get("description") if isinstance(raw.get("description"), str) else None
            _print_message(f"- {name}")
            if description:
                _print_message(f"  {description.strip()}")
        except RailWorkflowParseError:
            _print_message(f"- {path.stem} (invalid YAML)")
    return 0


def cmd_validate(workflow_name_or_path: str) -> int:
    try:
        file_path = find_workflow_file(workflow_name_or_path)
    except RailWorkflowNotFoundError as exc:
        _print_message(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        raw_data = load_raw_workflow(file_path)
    except RailWorkflowParseError as exc:
        _print_message(f"Syntax Error: {exc}", file=sys.stderr)
        return 1

    result = validate_workflow(raw_data)
    workflow_name = raw_data.get("name", file_path.stem)
    if result.is_valid:
        _print_message(f"\u2713 Workflow '{workflow_name}' ({file_path}) is valid.")
        return 0

    _print_message(
        f"\u2717 Validation failed for workflow '{workflow_name}' ({file_path}) with {len(result.errors)} error(s):",
        file=sys.stderr,
    )
    for error in result.errors:
        _print_message(f"  - {error}", file=sys.stderr)
    return 1


def cmd_status(workspace: Optional[str] = None, db_path: Optional[str] = None) -> int:
    workspace_path = Path(workspace).resolve() if workspace else Path.cwd().resolve()
    with StateStore(db_path=db_path) as store:
        run = store.get_active_run_for_workspace(workspace_path)
        if not run:
            _print_message(f"No active Rail workflow for workspace: {workspace_path}")
            return 0

        history = store.get_step_history(run.run_id)
        completed = [item.step_id for item in history if item.step_type != "end"]
        _print_message(f"Run: {run.run_id}")
        _print_message(f"Workflow: {run.workflow_name}")
        _print_message(f"Task: {run.task}")
        _print_message(f"Status: {run.status.value}")
        _print_message(f"Current step: {run.current_step or '(none)'}")
        if completed:
            _print_message("Completed: " + ", ".join(completed))
    return 0


def cmd_serve(workflows_dir: Optional[str] = None, db_path: Optional[str] = None) -> int:
    from rail.mcp.server import run_mcp_server

    try:
        run_mcp_server(workflows_dir=workflows_dir, db_path=db_path)
        return 0
    except (KeyboardInterrupt, SystemExit):
        return 0
    except Exception as exc:
        _print_message(f"MCP Server Error: {exc}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="rail", description="Rail - Workflow runtime for agentic coding tools")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser("init", help="Add or update Rail instructions in a repository")
    init_parser.add_argument("--workspace", help="Repository/workspace directory; defaults to current directory")

    subparsers.add_parser("workflows", help="List globally available workflows")

    validate_parser = subparsers.add_parser("validate", help="Validate a workflow definition")
    validate_parser.add_argument("workflow", help="Workflow name or file path (.yaml / .yml)")

    status_parser = subparsers.add_parser("status", help="Inspect the active workflow run for a workspace")
    status_parser.add_argument("--workspace", help="Repository/workspace directory; defaults to current directory")
    status_parser.add_argument("--db-path", help="Optional Rail SQLite database path")

    serve_parser = subparsers.add_parser("serve", help="Run MCP server over stdio")
    serve_parser.add_argument("--workflows-dir", help="Directory containing workflow YAML definitions", default=None)
    serve_parser.add_argument("--db-path", help="Path to SQLite database file", default=None)

    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(workspace=args.workspace)
    if args.command == "workflows":
        return cmd_workflows()
    if args.command == "validate":
        return cmd_validate(args.workflow)
    if args.command == "status":
        return cmd_status(workspace=args.workspace, db_path=args.db_path)
    if args.command == "serve":
        return cmd_serve(workflows_dir=args.workflows_dir, db_path=args.db_path)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
