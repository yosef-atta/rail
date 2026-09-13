# Rail

**Programmable workflows for coding agents.**

Rail is a lightweight workflow runtime that keeps coding agents inside a user-defined engineering process.

Instead of relying on an agent to remember when to plan, review, verify, ask for human approval, open a pull request, or stop, you define that process once as YAML and Rail controls the transitions.

> **The agent decides how to perform the current step. Rail decides which step the agent is allowed to perform.**

Rail is MCP-first, provider-agnostic, and intentionally small.

---

## Install

Rail currently targets Windows PowerShell.

Run:

```powershell
irm https://raw.githubusercontent.com/yosef-atta/rail/main/setup.ps1 | iex
```

The installer:

- creates `~/.rail/workflows`;
- installs the Rail CLI;
- seeds the three official workflows without overwriting existing user-edited copies;
- prints the MCP stdio configuration needed by your coding agent.

The official bundled workflows are:

- `default-agent`
- `default-agent-github`
- `default-human`

### Requirements

Rail requires Python tooling and supports installation through either:

- `uv` — preferred;
- `pip` — fallback.

When installed remotely, the installer installs Rail directly from this GitHub repository.

---

## Uninstall

To remove Rail completely:

```powershell
irm https://raw.githubusercontent.com/yosef-atta/rail/main/uninstall.ps1 | iex
```

The uninstaller removes:

- the installed Rail CLI/tool;
- the entire global Rail directory at `~/.rail`, including workflows and runtime state.

It does **not** modify your coding agent's MCP configuration because Rail does not automatically write provider configuration files during setup.

---

## Quick Start

### 1. Install Rail

```powershell
irm https://raw.githubusercontent.com/yosef-atta/rail/main/setup.ps1 | iex
```

### 2. See available workflows

```powershell
rail workflows
```

Expected defaults:

```text
default-agent
default-agent-github
default-human
```

### 3. Validate a workflow

```powershell
rail validate default-agent
```

You can also validate the other bundled workflows:

```powershell
rail validate default-agent-github
rail validate default-human
```

### 4. Initialize a project

From your repository:

```powershell
rail init
```

Rail adds or updates a managed block inside:

```text
AGENTS.md
CLAUDE.md
```

Existing content is preserved. Rail owns only the section between:

```text
<!-- RAIL:START -->
...
<!-- RAIL:END -->
```

### 5. Configure MCP

Rail exposes its runtime over stdio.

Generic MCP configuration:

```json
{
  "mcpServers": {
    "rail": {
      "command": "rail",
      "args": ["serve"]
    }
  }
}
```

Use the equivalent MCP configuration surface provided by your coding agent.

### 6. Ask the coding agent to use a workflow

For example:

```text
Implement authentication using the default-human workflow.
```

Rail is opt-in. A normal coding request does not automatically activate a workflow unless the user explicitly requests one.

---

## How Rail Works

A Rail run has exactly one active step.

```text
User task
   │
   ▼
Rail workflow
   │
   ▼
Current step
   │
   ├── coding agent performs the step
   │
   ▼
Agent reports outcome
   │
   ▼
Rail resolves the transition
   │
   ▼
Next step / human gate / terminal state
```

The agent does not choose the next workflow step itself.

For branching steps, the agent reports an outcome such as:

```text
approved
```

Rail reads the workflow definition and decides where `approved` leads.

> **Agents report outcomes. Rail controls transitions.**

This keeps workflow state outside the model's memory and makes the process persistent across long tasks, context compaction, and agent handoffs.

---

## Official Workflows

### `default-agent`

Fully agent-driven local workflow:

```text
planner
  ↓
plan-reviewer
  ↓
code
  ↓
verifier
  ↓
reviewer
  ↓
reporter
  ↓
completed
```

The plan reviewer, verifier, and reviewer may reject the work. A rejection intentionally stops the workflow rather than silently continuing.

The reporter analyzes the final repository, commits the implementation, and reports the result. It does not push, open a pull request, or merge.

---

### `default-agent-github`

Fully agent-driven workflow including GitHub delivery:

```text
planner
  ↓
plan-reviewer
  ↓
code
  ↓
verifier
  ↓
reviewer
  ↓
github
  ↓
reporter
  ↓
completed
```

The GitHub step instructs the agent to:

1. commit the implementation;
2. push the current feature branch;
3. open a pull request to the intended base branch;
4. merge using a normal merge commit;
5. never squash;
6. never rebase;
7. switch to the base branch;
8. pull the latest base branch.

---

### `default-human`

Human-supervised workflow:

```text
plan
  ↓
human plan review
  ├── reject ───────────────→ plan
  └── approve
         ↓
        code
         ↓
       verify
  ├── changes required ─────→ code
  └── approved
         ↓
       review
  ├── changes required ─────→ code
  └── approved
         ↓
   human manual review
  ├── reject ───────────────→ code
  └── approve
         ↓
      finalize
         ↓
      completed
```

Human gates cannot be approved or bypassed by the coding agent itself.

---

## CLI Reference

Rail's CLI is intentionally focused on setup, discovery, validation, inspection, and serving MCP.

Runtime mutation remains MCP-first.

### Initialize the current project

```powershell
rail init
```

Initialize another directory:

```powershell
rail init --workspace C:\path\to\project
```

---

### List available workflows

```powershell
rail workflows
```

Rail discovers global workflow files from:

```text
~/.rail/workflows/
```

Both `.yml` and `.yaml` are supported.

---

### Validate a workflow

```powershell
rail validate default-human
```

Validation happens before execution and catches invalid step types, missing transitions, invalid result options, missing targets, malformed terminal steps, and other ambiguous workflow definitions.

---

### Inspect the active run

```powershell
rail status
```

For another workspace:

```powershell
rail status --workspace C:\path\to\project
```

When a workflow is active, status includes its run ID, workflow name, task, run status, current step, and completed progress.

---

### Start the MCP server

```powershell
rail serve
```

Rail uses stdio for MCP communication.

---

## Workflow Files

Global workflows live at:

```text
~/.rail/
└── workflows/
    ├── default-agent.yml
    ├── default-agent-github.yml
    └── default-human.yml
```

You may add your own `.yml` or `.yaml` workflow files to the same directory.

A minimal workflow looks like:

```yaml
version: "0.1"
name: simple-example
start: plan

steps:
  plan:
    type: agent
    role: main
    prompt: |
      Create an implementation plan.
      Do not modify code yet.
    next: implement

  implement:
    type: agent
    role: main
    prompt: |
      Implement the approved plan.
    next: done

  done:
    type: end
```

---

## Supported Step Types

Rail POC v0.1 supports exactly three step types.

### `agent`

Work performed by the coding agent or one of its subagents.

```yaml
review:
  type: agent
  role: subagent
  name: reviewer
  prompt: |
    Review the implementation critically.
  next: done
```

Supported roles:

```text
main
subagent
```

A `subagent` step requires a `name`.

Rail does not define provider-specific subagent configuration. The surrounding coding tool decides how to create or invoke the requested subagent.

---

### `human`

A mandatory human gate.

```yaml
manual_review:
  type: human
  message: |
    Manually verify the implementation.
  transitions:
    approve: done
    changes_required: implement
```

Rail pauses at the gate until a human resolves one of the declared actions.

---

### `end`

A terminal workflow step.

Successful completion:

```yaml
done:
  type: end
```

The omitted status defaults to:

```text
completed
```

Intentional workflow stop:

```yaml
stopped:
  type: end
  status: stopped
```

Supported terminal outcomes are therefore:

```text
completed
stopped
```

---

## Results and Branching

Agent steps may return a predefined choice result:

```yaml
result:
  type: choice
  options:
    - approved
    - rejected

transitions:
  approved: implement
  rejected: stopped
```

The agent reports only the result value. Rail resolves the destination.

Loops require no separate retry primitive. They can be expressed directly through transitions:

```yaml
transitions:
  approved: review
  changes_required: implement
```

---

## Run Statuses

A Rail run may be in one of these states:

```text
running
paused_human
completed
stopped
failed
```

### `running`

An agent step is active.

### `paused_human`

Rail is waiting for explicit human input.

### `completed`

The workflow reached a successful terminal end step.

### `stopped`

The workflow intentionally terminated because of a declared decision or quality gate, such as a rejected review.

`stopped` is terminal and inactive.

### `failed`

Execution failed because of a runtime error rather than a workflow decision.

---

## MCP-First Runtime

Rail deliberately does **not** expose CLI commands such as:

```text
rail start
rail complete
rail approve
rail transition
```

The CLI is not intended to mirror the runtime API.

Coding agents interact with workflow execution through MCP, while humans use the CLI mainly for installation, discovery, validation, and inspection.

This keeps Rail independent from any individual provider or agent product.

Conceptually:

```text
Codex ───────────┐
Claude Code ─────┤
OpenCode ────────┤
Antigravity ─────┤
Other MCP agents ┤
                 ▼
                MCP
                 │
                 ▼
                Rail
```

---

## Project Initialization

`rail init` teaches compatible coding agents how to behave when a user explicitly requests a Rail workflow.

The managed instructions require the agent to:

1. start the requested Rail workflow before planning or editing;
2. follow only the current Rail step;
3. never skip, reorder, invent, or infer workflow steps;
4. never transition the workflow itself;
5. report agent-step completion through Rail;
6. stop at human gates and stopped terminal states;
7. never approve or bypass a human gate;
8. continue only after the human resolves the gate;
9. query Rail when workflow state is unclear.

Running `rail init` repeatedly is safe: Rail updates only its own managed block.

---

## Design Principles

Rail's POC is intentionally narrow.

It currently avoids:

- command steps;
- GitHub-specific runtime integrations;
- nested workflows;
- parallel execution;
- expression languages;
- workflow variables;
- a dedicated retry primitive;
- provider-specific subagent configuration;
- automatic provider configuration edits.

The goal is to prove the core execution model before growing the language or runtime surface.

---

## Development

Clone the repository and install locally:

```powershell
git clone https://github.com/yosef-atta/rail.git
cd rail
.\setup.ps1
```

When `setup.ps1` is executed from a local checkout, Rail is installed as an editable package so local code changes are reflected during development.

Run the test suite:

```powershell
python -m pytest
```

The current Phase 5 implementation is covered by tests for the CLI, workflow loader, models, validator, runtime, storage, MCP behavior, default workflow contracts, setup behavior, and terminal outcomes.

---

## POC Roadmap

### Phase 1 — Workflow Language

- [x] Define workflow schema.
- [x] Support `agent`, `human`, and `end` steps.
- [x] Support linear `next` transitions.
- [x] Support choice-based branching.
- [x] Support human gates.
- [x] Support loops through transitions.
- [x] Add static workflow validation.

### Phase 2 — Runtime

- [x] Add persistent run state.
- [x] Track the current step.
- [x] Track step history.
- [x] Resolve transitions in the runtime.
- [x] Support completed and failed runs.
- [x] Support human-paused runs.
- [x] Support intentional stopped terminal runs.

### Phase 3 — MCP Runtime

- [x] Expose workflow runtime over MCP.
- [x] Allow agents to start workflows.
- [x] Return the current active step.
- [x] Accept agent-step completion/results.
- [x] Resolve human actions.
- [x] Expose workflow status and history.

### Phase 4 — Workflow Discovery

- [x] Load workflows from the global Rail directory.
- [x] Support `.yml` and `.yaml` files.
- [x] Keep workflows reusable across repositories.

### Phase 5 — User Setup and Defaults

- [x] Add `rail init`.
- [x] Add `rail workflows`.
- [x] Add `rail validate`.
- [x] Add `rail status`.
- [x] Add managed Rail blocks to `AGENTS.md` and `CLAUDE.md`.
- [x] Add Windows PowerShell setup.
- [x] Add remote one-line installation.
- [x] Add complete uninstall support.
- [x] Add three official default workflows.

---

## Status

Rail is currently a **POC**.

The core workflow language, persistent runtime, MCP execution path, CLI setup/inspection commands, official default workflows, remote installer, and uninstaller are implemented.

The project is intentionally keeping the surface area small while the workflow execution model is validated in real coding-agent usage.
