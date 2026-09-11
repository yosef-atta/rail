"""Rail command line interface."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from rail.core.exceptions import (
    RailWorkflowNotFoundError,
    RailWorkflowParseError,
)
from rail.core.loader import find_workflow_file, load_raw_workflow
from rail.core.validator import validate_workflow


def _print_message(msg: str, file=sys.stdout) -> None:
    try:
        print(msg, file=file)
    except UnicodeEncodeError:
        # Fallback for terminals that cannot encode UTF-8 symbols
        safe_msg = msg.replace("\u2713", "[OK]").replace("\u2717", "[FAIL]")
        print(safe_msg, file=file)


def cmd_validate(workflow_name_or_path: str) -> int:
    """Validate a workflow definition file or global workflow by name."""
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
    wf_name = raw_data.get("name", file_path.stem)
    if result.is_valid:
        _print_message(f"\u2713 Workflow '{wf_name}' ({file_path}) is valid.")
        return 0

    _print_message(
        f"\u2717 Validation failed for workflow '{wf_name}' ({file_path}) with {len(result.errors)} error(s):",
        file=sys.stderr,
    )
    for err in result.errors:
        _print_message(f"  - {err}", file=sys.stderr)

    return 1


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="rail", description="Rail - Workflow runtime for agentic coding tools")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    validate_parser = subparsers.add_parser("validate", help="Validate a workflow definition")
    validate_parser.add_argument("workflow", help="Workflow name or file path (.yaml / .yml)")

    args = parser.parse_args(argv)

    if args.command == "validate":
        return cmd_validate(args.workflow)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
