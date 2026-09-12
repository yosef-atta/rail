# Rail

**Programmable workflows for coding agents.**

Rail is a lightweight workflow runtime for agentic coding tools.

Instead of asking a coding agent to:

> Implement authentication.

and relying on the agent to remember your preferred engineering process, Rail lets you define that process as a workflow and requires the agent to move through it step by step.

For example:

```text
Plan
  ↓
Plan Review
  ↓
Implementation
  ↓
Verification
  ↓
Human Review
  ↓
Done
```

The workflow is defined once in YAML and can then be reused across projects and coding agents.

A user can ask:

```text
Implement authentication using the default workflow.
```

The coding agent starts the requested Rail workflow and follows the currently active step until the workflow is complete.

Rail's core idea is simple:

> **The agent decides how to perform the current step. Rail decides which step the agent is allowed to perform.**

---

## Why Rail?

Agentic coding works best when complex tasks are broken into disciplined engineering steps.

A typical real-world workflow may look like:

```text
Understand task
→ Plan
→ Review plan
→ Implement
→ Verify
→ Review
→ Manual testing
→ Pull request
→ Merge
```

Without external workflow control, the coding agent itself is responsible for remembering and respecting that process.

That creates several problems:

* the agent may start implementation before planning is finished;
* review steps may be skipped;
* verification may happen too early or too late;
* human approval gates may be forgotten;
* different sessions may follow slightly different processes;
* context compaction or agent handoffs may lose workflow state;
* the user has to repeatedly supervise the process manually.

Rail moves the engineering process outside the agent.

The workflow becomes persistent, explicit, reusable, and controlled by a runtime rather than by the agent's memory.

---

# POC Goal

The Rail POC intentionally solves one narrow problem:

> **Can an external workflow runtime reliably keep an agentic coding tool inside a user-defined engineering process?**

The POC is not intended to be a general-purpose orchestration platform.

It intentionally avoids advanced features until the core execution model has been proven.

---

# Core Model

A Rail workflow contains ordered or branching **steps**.

At any point, a workflow run has exactly one current step.

The coding agent may work only on that step.

When the step is complete, the agent reports completion to Rail.

Rail then determines the next step from the workflow definition.

The agent does **not** choose or infer the next workflow step itself.

```text
User Task
   │
   ▼
Rail Workflow
   │
   ▼
Current Step
   │
   ├── Agent performs current work
   │
   ▼
Step Completion
   │
   ▼
Rail determines transition
   │
   ▼
Next Step
```

---

# Workflow Files

Rail workflows are stored globally as YAML files.

Conceptually:

```text
~/.rail/
└── workflows/
    ├── default.yaml
    ├── careful-feature.yaml
    └── fast-fix.yml
```

A workflow is therefore reusable across repositories.

Workflows may use either:

```text
.yml
```

or:

```text
.yaml
```

---

# Workflow Language — POC v0.1

The POC deliberately keeps the workflow language small.

Example:

```yaml
version: "0.1"

name: default

description: >
  Default coding workflow for planned and verified implementation.

start: plan

steps:
  plan:
    type: agent
    role: main

    prompt: |
      Create an implementation plan for the requested task.
      Do not modify code.

    next: review_plan

  review_plan:
    type: agent
    role: subagent

    name: plan-reviewer

    prompt: |
      Review the proposed implementation plan critically.

      Look for:
      - missing work;
      - incorrect assumptions;
      - unnecessary complexity;
      - architectural risks;
      - verification gaps.

    result:
      type: choice
      options:
        - approved
        - changes_required

    transitions:
      approved: implement
      changes_required: plan

  implement:
    type: agent
    role: main

    prompt: |
      Implement the approved plan.

    next: verify

  verify:
    type: agent
    role: main

    prompt: |
      Verify the implementation.

      Run the relevant tests and checks.
      Fix any problems discovered during verification before completing this step.

    next: human_review

  human_review:
    type: human

    message: |
      Review and manually verify the implementation.

    transitions:
      approve: done
      changes_required: implement

  done:
    type: end
```

---

# Supported Step Types

The POC supports exactly three step types.

## `agent`

Work performed by an AI coding agent.

```yaml
plan:
  type: agent
  role: main

  prompt: |
    Create an implementation plan.

  next: implement
```

Every agent step requires a `role`.

---

## `human`

A workflow gate that requires explicit human input.

```yaml
manual_review:
  type: human

  message: |
    Manually verify the implementation.

  transitions:
    approve: done
    changes_required: implement
```

Rail pauses the workflow at a human step.

The coding agent cannot complete or bypass the gate itself.

---

## `end`

Marks successful workflow completion.

```yaml
done:
  type: end
```

An `end` step cannot have `next` or `transitions`.

---

# Agent Roles

The POC supports two agent roles.

## `main`

The currently active coding agent performs the step.

```yaml
role: main
```

For example, if Rail is being used from Claude Code, Codex, OpenCode, Antigravity, or another compatible environment, the primary agent performs the work.

---

## `subagent`

The main coding agent delegates the step to a subagent.

```yaml
role: subagent
name: plan-reviewer
```

A subagent step requires a `name`.

Example:

```yaml
review:
  type: agent
  role: subagent
  name: code-reviewer

  prompt: |
    Review the implementation critically.

  next: done
```

For the POC, Rail does not define provider-specific subagent configuration.

The surrounding agentic coding tool remains responsible for creating or invoking the subagent.

---

# Prompts

Every `agent` step contains one inline `prompt`.

```yaml
prompt: |
  Review the implementation for correctness.
```

The workflow author has complete control over this prompt.

The prompt may contain any instructions required for that step.

The POC intentionally does **not** support:

```text
system_prompt
prepend_prompt
append_prompt
prompt inheritance
prompt templates
prompt files
reusable prompt definitions
```

There is one prompt per agent step.

---

# Linear Transitions

If a step always moves to one specific step, use `next`.

```yaml
implement:
  type: agent
  role: main

  prompt: |
    Implement the approved plan.

  next: verify
```

---

# Choice Results

Agent steps may return one predefined result.

```yaml
result:
  type: choice

  options:
    - approved
    - changes_required
```

These results can control workflow branching:

```yaml
transitions:
  approved: implement
  changes_required: plan
```

The agent reports only the result.

It does not choose the destination step.

For example, the agent may report:

```text
approved
```

Rail reads the workflow and determines:

```text
approved → implement
```

This distinction is intentional.

> **Agents report outcomes. Rail controls transitions.**

---

# Human Gates

Human steps also use predefined transitions.

```yaml
human_review:
  type: human

  message: |
    Review the final implementation.

  transitions:
    approve: done
    changes_required: implement
```

When Rail reaches this step, execution pauses.

Conceptually:

```text
Workflow paused

Current step: human_review

Review the final implementation.

Available actions:

- approve
- changes_required
```

No agent may automatically approve the gate.

---

# Loops

The POC does not need a separate retry or loop primitive.

Loops can already be expressed through transitions.

For example:

```yaml
review:
  type: agent
  role: subagent
  name: reviewer

  prompt: |
    Review the implementation.

  result:
    type: choice

    options:
      - approved
      - changes_required

  transitions:
    approved: human_review
    changes_required: implement
```

This creates:

```text
implement
   ↓
review
   │
   ├── approved ───────────→ human_review
   │
   └── changes_required ──→ implement
```

---

# Validation

Rail validates workflows before execution.

Invalid workflows must fail before a run starts.

POC validation includes at least the following rules:

* `version` is required.
* `name` is required.
* `start` is required.
* `steps` is required.
* `start` must reference an existing step.
* every `next` target must exist;
* every transition target must exist;
* a step must use a supported `type`;
* an `agent` step requires `role`;
* `role` must be `main` or `subagent`;
* a `subagent` step requires `name`;
* an `agent` step requires `prompt`;
* a `human` step requires `transitions`;
* an `end` step cannot contain `next`;
* an `end` step cannot contain `transitions`;
* `next` and `transitions` cannot exist on the same step;
* `result.type` may only be `choice`;
* every choice option must have a corresponding transition;
* transitions for choice-based agent steps must correspond to valid result options.

Additional validation may be added where necessary to prevent ambiguous workflow execution.

---

# Agentic Coding Tool Integration

Rail is designed to avoid provider-specific integrations.

The POC should not depend specifically on:

* Codex;
* Claude Code;
* OpenCode;
* Antigravity;
* Cursor;
* Pi;
* or another individual coding agent.

Instead, Rail exposes its runtime through MCP.

Any agentic coding environment capable of using MCP can therefore interact with the same Rail runtime.

```text
Claude Code ─────┐
Codex ───────────┤
OpenCode ────────┤
Antigravity ─────┤
Pi + MCP ────────┤
Other Agents ────┤
                 ▼
                MCP
                 │
                 ▼
              Rail Core
```

MCP registration is performed manually by the user.

Provider-specific automatic integrations are outside the POC.

---

# Project Initialization

Rail uses project initialization only to establish its agent instructions.

A project does not require a Rail-specific database, workflow directory, or repository configuration.

Running:

```powershell
rail init
```

adds or updates a Rail-managed section at the end of:

```text
AGENTS.md
CLAUDE.md
```

Existing user content remains untouched.

Rail owns only its marked block.

Conceptually:

```markdown
<!-- RAIL:START -->

## Rail Workflow Execution

This project supports externally controlled coding workflows through Rail.

When the user explicitly requests a task using a Rail workflow, for example:

`Implement authentication using the default workflow`

you MUST:

1. Start the requested workflow before planning, editing files, or implementing the task.
2. Follow only the current workflow step returned by Rail.
3. Never skip, reorder, invent, or infer workflow steps.
4. Never transition to another workflow step yourself.
5. Report completion through Rail after completing an agent step.
6. Stop immediately when Rail reaches a human step.
7. Never approve or bypass a human gate yourself.
8. Continue only after the human gate has been explicitly resolved.
9. If workflow state is unclear, query Rail before continuing.

Rail is authoritative over workflow execution.

<!-- RAIL:END -->
```

Running `rail init` again updates only this managed block.

---

# Opt-In Execution

Rail does not control every coding task automatically.

The workflow system activates only when the user explicitly requests a workflow.

For example:

```text
Implement authentication.
```

does not require Rail.

But:

```text
Implement authentication using the default workflow.
```

does.

Other equivalent natural-language requests should also be recognized, such as:

```text
Use the careful-feature workflow to implement authentication.
```

The project instructions tell the coding agent to start Rail whenever the user explicitly requests a Rail workflow.

---

# CLI

The POC uses the CLI for setup, discovery, validation, and inspection.

The CLI is **not** a mirror of the workflow runtime.

Initial commands:

```powershell
rail init
```

Initialize Rail instructions in the current repository.

```powershell
rail workflows
```

List globally available workflows.

```powershell
rail validate <workflow>
```

Validate a workflow definition.

```powershell
rail status
```

Inspect the active workflow run for the current project.

The POC does not expose runtime mutation commands such as:

```text
rail start
rail complete
rail approve
rail transition
```

Workflow execution is MCP-first.

A runtime CLI transport may be added later if there is real demand from coding tools without MCP support.

---

# MCP Tools

The Rail POC exposes five workflow tools.

## `workflow_start`

Starts a workflow run.

Conceptual input:

```yaml
workflow: default
task: Implement authentication
```

Rail:

1. locates the global workflow;
2. validates it;
3. creates a workflow run;
4. records the requested task;
5. activates the `start` step;
6. returns the current step instructions.

Conceptual response:

```text
Run: R-000014
Workflow: default
Status: running

Current step: plan
Type: agent
Role: main

Instructions:
Create an implementation plan for the requested task.
Do not modify code.
```

---

## `workflow_status`

Returns the current workflow state.

Conceptually:

```text
Run: R-000014
Workflow: default
Task: Implement authentication

Status: running

Current step:
review_plan

Completed:
✓ plan

Current:
→ review_plan

Pending:
○ implement
○ verify
○ human_review
○ done
```

This is useful after:

* context compaction;
* session restarts;
* agent handoffs;
* uncertainty about current workflow state;
* user status requests.

---

## `workflow_step`

Returns authoritative instructions for the current step.

Conceptually:

```text
Current step: implement

Type: agent
Role: main

Prompt:
Implement the approved plan.
```

This tool is execution-oriented.

`workflow_status` explains where the workflow is.

`workflow_step` tells the agent what it is currently allowed to do.

---

## `workflow_complete_step`

Completes the currently active agent step.

For a linear step:

```yaml
next: verify
```

the agent reports completion and Rail performs the transition.

For a choice step:

```yaml
result:
  type: choice

  options:
    - approved
    - changes_required
```

the agent must provide one valid result.

Conceptually:

```yaml
result: approved
```

Rail then resolves:

```yaml
transitions:
  approved: implement
```

and activates `implement`.

The agent cannot provide an arbitrary destination step.

---

## `workflow_human_action`

Resolves a human gate.

For example:

```yaml
action: approve
```

Rail validates the action against the current human step:

```yaml
transitions:
  approve: done
  changes_required: implement
```

and performs the corresponding transition.

A human step cannot be completed through `workflow_complete_step`.

---

# Enforcement

Rail's runtime is authoritative over workflow state.

Important POC invariants include:

### One Current Step

A workflow run always has one authoritative current step until completion.

### Agents Cannot Choose Transitions

Agents may report results.

They may not supply arbitrary destination steps.

### Human Steps Cannot Be Completed by Agents

When a human gate becomes active, agent execution stops.

### Invalid Results Are Rejected

If the workflow expects:

```text
approved
changes_required
```

then another result such as:

```text
mostly_approved
```

is invalid.

### Completed Steps Cannot Be Silently Skipped

Transitions happen only through the runtime.

### Workflow State Survives Agent Context

The authoritative state is external to the coding agent's conversation context.

---

# Persistence

Workflow runs must be durable.

A restart of the coding agent or MCP server should not cause Rail to forget where the workflow stopped.

The POC state model needs to persist at least:

```text
run_id
workflow
task
current_step
status
step_history
step_results
created_at
updated_at
```

SQLite is a suitable implementation for the POC.

The persistence implementation is internal to Rail and is not part of the workflow language.

---

# Architecture

The initial architecture should remain intentionally small.

```text
                    Rail
                     │
        ┌────────────┴────────────┐
        │                         │
       CLI                       MCP
        │                         │
        └────────────┬────────────┘
                     │
                 Core Engine
                     │
         ┌───────────┼───────────┐
         │           │           │
      Loader      Validator    Runtime
                                 │
                              State Store
```

The same core implementation should power both CLI inspection commands and MCP execution.

---

# What the POC Does Not Include

The following features are intentionally excluded.

## No Provider-Specific Integrations

No special Codex, Claude Code, OpenCode, Antigravity, Pi, or Cursor implementation.

Rail communicates through MCP.

---

## No Runtime CLI Mirror

The CLI does not duplicate every MCP operation.

MCP remains the primary workflow execution interface.

---

## No Command Steps

This is not part of POC v0.1:

```yaml
type: command
run: pnpm test
```

Instead, an agent step may instruct the coding agent to run the appropriate commands.

---

## No GitHub Action Steps

Not included:

```yaml
type: action
action: github.create_pr
```

A workflow may instead contain an agent step instructing the coding agent to create the pull request using its existing tools.

---

## No Nested Workflows

Not included:

```yaml
type: workflow
use: verification
```

---

## No Parallel Execution

Not included:

```yaml
parallel:
  - security_review
  - architecture_review
```

POC workflows execute one active step at a time.

---

## No Expression Language

Not included:

```yaml
when: output.score > 80
```

Branching happens only through explicit choice results.

---

## No Workflow Variables

Not included:

```text
${task}
${repo}
${previous.output}
```

The runtime is responsible for supplying relevant workflow state to the agent.

---

## No Explicit Context Configuration

Not included:

```yaml
context:
  include:
  exclude:
```

---

## No Tool Permission System

Not included:

```yaml
tools:
  allow:
  deny:
```

---

## No Retry Primitive

Not included:

```yaml
retry:
  max: 3
```

Retries and correction loops can be represented through transitions.

---

## No Timeouts

No workflow, step, or human-gate timeout configuration in the POC.

---

## No Approval Policies

The POC does not define:

```text
users
teams
required reviewers
approval counts
permissions
```

A human gate simply requires explicit human resolution.

---

## No Formal Artifacts

The POC does not expose an artifact system for plans, reports, patches, or review results.

Rail stores workflow progress and step results only as required for execution.

---

## No Structured Output Schemas

The only structured agent result supported in POC v0.1 is:

```yaml
result:
  type: choice
```

There is no arbitrary JSON Schema output system.

---

## No Reusable Agent Definitions

Not included:

```yaml
agents:
  architecture-reviewer:
    ...
```

Agent configuration belongs directly to each step.

---

## No Reusable Prompt Definitions

Prompts remain inline.

---

# Example Workflow

A more complete POC workflow may look like:

```yaml
version: "0.1"

name: careful-feature

description: >
  Plan, independently review, implement, verify,
  and manually inspect a feature.

start: plan

steps:
  plan:
    type: agent
    role: main

    prompt: |
      Inspect the repository and create a concrete implementation plan.

      Do not modify project files during this step.

    next: review_plan

  review_plan:
    type: agent
    role: subagent
    name: plan-reviewer

    prompt: |
      Review the proposed implementation plan independently.

      Check whether it:
      - solves the requested task;
      - fits the existing architecture;
      - avoids unnecessary complexity;
      - includes appropriate verification;
      - misses any important implementation work.

      Return either approved or changes_required.

    result:
      type: choice

      options:
        - approved
        - changes_required

    transitions:
      approved: implement
      changes_required: plan

  implement:
    type: agent
    role: main

    prompt: |
      Implement the approved plan.

      Keep the implementation scoped to the requested task.

    next: verify

  verify:
    type: agent
    role: main

    prompt: |
      Verify the completed implementation.

      Run the relevant automated checks and inspect the implementation for obvious regressions.

      Fix problems found during this step before completing it.

    next: human_review

  human_review:
    type: human

    message: |
      Manually review and test the implementation.

    transitions:
      approve: done
      changes_required: implement

  done:
    type: end
```

---

# Example Execution

User:

```text
Implement authentication using the careful-feature workflow.
```

The agent starts Rail:

```text
workflow_start
```

Rail activates:

```text
plan
```

The agent creates the plan and reports completion:

```text
workflow_complete_step
```

Rail activates:

```text
review_plan
```

The main agent delegates the review to the requested subagent.

The reviewer reports:

```text
approved
```

The main agent reports the result through Rail:

```text
workflow_complete_step(result="approved")
```

Rail activates:

```text
implement
```

After implementation:

```text
workflow_complete_step
```

Rail activates:

```text
verify
```

After verification:

```text
workflow_complete_step
```

Rail reaches:

```text
human_review
```

Execution stops.

The human manually verifies the implementation and approves it.

Rail receives:

```text
workflow_human_action(action="approve")
```

Rail transitions to:

```text
done
```

The run becomes:

```text
completed
```

---

# Design Principles

## Workflow State Lives Outside the Agent

The coding agent's context is not the source of truth.

Rail is.

---

## Workflows Describe Process, Not Implementation

Rail does not tell coding tools how to read files, edit code, run tests, use Git, or create pull requests.

The surrounding coding agent already has those capabilities.

Rail controls when those activities should happen.

---

## Minimal Language, Composable Behavior

The POC intentionally prefers a few primitives that can be combined.

For example, retries do not require a retry feature when a transition can already form a loop.

---

## No Hardcoded Engineering Process

Rail itself does not decide that software must always follow:

```text
plan → code → test → review
```

That is merely one possible workflow.

Users define their own process.

---

## Human Gates Are Real Gates

A human review step is not a suggestion inside a prompt.

It is workflow state.

Execution does not continue until the human resolves it.

---

## Agent-Agnostic by Default

Workflow semantics should remain independent of the model or coding tool executing them.

---

## POC Before Platform

Rail should prove reliable external workflow enforcement before adding orchestration features.

---

# Roadmap

## POC — Workflow Enforcement

The initial milestone proves the core idea.

* [x] Define and validate Workflow Language v0.1.
* [x] Load global `.yml` and `.yaml` workflows.
* [x] Implement the workflow runtime.
* [x] Implement persistent workflow runs.
* [x] Implement `main` agent steps.
* [x] Implement `subagent` steps.
* [x] Implement choice results.
* [x] Implement human gates.
* [x] Implement workflow transitions and loops.
* [ ] Implement MCP server.
* [ ] Add `workflow_start`.
* [ ] Add `workflow_status`.
* [ ] Add `workflow_step`.
* [ ] Add `workflow_complete_step`.
* [ ] Add `workflow_human_action`.
* [ ] Add `rail init`.
* [ ] Add `rail workflows`.
* [x] Add `rail validate`.
* [ ] Add `rail status`.
* [ ] Add managed Rail blocks to `AGENTS.md` and `CLAUDE.md`.
* [ ] Add `setup.ps1` for local installation and MCP setup guidance.
* [ ] Test the same workflow across multiple agentic coding tools.
* [ ] Verify that agents reliably stop at human gates.
* [ ] Verify that workflow state survives session and MCP restarts.

### POC Success Criteria

The POC succeeds if a user can:

1. define a workflow globally;
2. initialize an arbitrary repository with Rail instructions;
3. manually register Rail's MCP server with a compatible coding tool;
4. ask that coding agent to perform a task using a named workflow;
5. observe the agent follow the workflow in order;
6. use branching and loops;
7. use main-agent and subagent steps;
8. stop execution at a human gate;
9. resume only after explicit human approval;
10. retain workflow state across interrupted sessions.

---

## Post-POC

Only after the POC proves the execution model should Rail consider features such as:

* runtime CLI transport for environments without MCP;
* richer run history;
* workflow cancellation and recovery;
* reusable agents;
* reusable prompts;
* workflow variables;
* structured outputs;
* workflow artifacts;
* context control;
* tool permissions;
* command executors;
* external actions;
* nested workflows;
* parallel steps;
* retries and timeout policies;
* advanced human approval policies;
* reusable workflow libraries;
* workflow composition;
* richer conditional expressions;
* provider-specific adapters where they provide meaningful value.

These are intentionally not commitments for the POC.

---

# Biggest & Safe Implementation Slices

To guarantee that Rail is built safely, reliably, and completely without deadlocks or architectural rework, the POC Roadmap is broken into **six strictly ordered, cohesive implementation slices**.

### Slicing Principles:
1. **Biggest (Cohesive & Complete)**: Each slice represents a complete, self-contained functional layer rather than fragmented, fragile micro-tasks.
2. **Safe (Strict Dependency Invariants)**: The order of phases is architecturally unskippable. Phase $N$ strictly consumes and builds upon the proven contracts established in Phase $N-1$. No phase can be implemented ahead of its dependencies.
3. **100% POC Coverage**: Completing all six phases successfully finishes 100% of the POC Roadmap items and satisfies all 10 POC Success Criteria without missing components or unresolved edge cases.

```text
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: Workflow Specification, Loader & Static Validator   │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Validated Domain Models)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: Persistence Layer & Durable State Store (SQLite)    │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Durable Storage Contract)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 3: Workflow Runtime & Transition State Machine         │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Authoritative Engine API)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 4: MCP Server & Tool Protocol Surface                  │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Agent Communication Layer)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 5: CLI, Project Instructions & Setup Tooling           │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Operational & Onboarding)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 6: Multi-Agent Integration & End-to-End Verification   │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
                     100% Complete & Verified
```

---

## Phase 1: Workflow Specification, Loader & Static Validator

### Purpose
Establish the foundational data structures, file loader, and comprehensive validation engine for Workflow Language v0.1.

### Why This Phase Must Come First (Dependency Invariant)
* You cannot persist, execute, inspect, or expose workflows that cannot be parsed, deserialized, and validated.
* Workflows define the contract for everything that follows: step types, roles, prompts, choices, transitions, and gates.
* Validating statically at load time guarantees that invalid definitions (such as missing targets, dangling loops, invalid step roles, or ambiguous transitions) are caught before any runtime execution state is instantiated.

### Roadmap Items Covered
* [x] Define and validate Workflow Language v0.1.
* [x] Load global `.yml` and `.yaml` workflows.
* [x] Add `rail validate` (core validation engine).

### Scope & Deliverables
1. **Schema & Domain Models**:
   * Data structures for `Workflow`, `Step` (`AgentStep`, `HumanStep`, `EndStep`), `Role` (`main`, `subagent`), and `ChoiceResult`.
2. **Filesystem Loader**:
   * Discovery and parsing of `.yml` and `.yaml` files from `~/.rail/workflows/`.
3. **Static Validator Rules**:
   * `version`, `name`, `start`, and `steps` presence.
   * `start` step existence in `steps`.
   * Referencing integrity: every `next` step and every `transitions` target must exist.
   * Role enforcement: `agent` steps require `role` (`main` or `subagent`) and non-empty `prompt`.
   * Subagent constraint: `subagent` steps require `name`.
   * Human gate constraint: `human` steps require `message` and `transitions`.
   * End step constraint: `end` steps cannot declare `next` or `transitions`.
   * Mutual exclusivity: a step cannot declare both `next` and `transitions`.
   * Choice validation: `result.type: choice` options must match step `transitions` keys exactly 1:1.
   * Guard against excluded features: command steps, nested workflows, parallel steps, variables, and expressions.

### Acceptance & Verification Gate
* Unit tests parsing valid workflows (`default.yaml`, `careful-feature.yaml`).
* Unit tests rejecting every invalid variant (missing start, unreachable step, dangling transition target, missing prompt, missing role, invalid role, choice/transition mismatch).

---

## Phase 2: Persistence Layer & Durable State Store

### Purpose
Implement the durable SQLite storage layer that records runs, step executions, outcomes, and workflow transitions independently of agent memory.

### Why This Phase Strictly Depends on Phase 1 & Cannot Be Reordered
* **Depends on Phase 1**: The database tables and queries model state transitions over validated workflow names, step IDs, and choice outcomes defined in Phase 1.
* **Why it cannot be deferred past Phase 3**: Rail's central architectural invariant is that *"Workflow State Lives Outside the Agent and Survives Process/Session Restarts"*. If execution logic (Phase 3) is written before persistence, the runtime will inevitably rely on volatile in-memory state, creating fragile abstractions that require invasive refactoring later. Writing the persistence layer first forces the runtime to be state-store-native from line one.

### Roadmap Items Covered
* [x] Implement persistent workflow runs.


### Scope & Deliverables
1. **SQLite Database Initialization**:
   * Embedded SQLite storage located at `~/.rail/rail.db`.
   * Auto-migration and index setup on startup.
2. **Relational Schema**:
   * `runs`: `run_id` (e.g. `R-000001`), `workflow_name`, `task`, `status` (`running`, `paused_human`, `completed`, `failed`), `current_step`, `created_at`, `updated_at`.
   * `step_history`: `run_id`, `step_id`, `step_type`, `role`, `result`, `transition_taken`, `started_at`, `completed_at`.
3. **Repository Store API**:
   * Atomic operations for `create_run()`, `get_run(run_id)`, `update_run_step()`, `record_step_completion()`, `record_human_action()`, and `get_active_run_for_workspace()`.

### Acceptance & Verification Gate
* Persistence unit tests: create a run, write step history, simulate sudden process termination, open a new database connection, and verify exact state recovery.

---

## Phase 3: Workflow Runtime & Transition State Machine

### Purpose
Build the core execution engine that drives workflow progression, manages active steps, handles choices and cyclic loops, and strictly enforces human gates.

### Why This Phase Strictly Depends on Phase 2 & Cannot Be Reordered
* **Depends on Phase 1 & 2**: The runtime consumes validated workflow graphs (Phase 1) and commits state transitions through the persistent store (Phase 2).
* **Why it cannot be implemented before Phase 1 or 2**: A state machine cannot transition without a graph to traverse (Phase 1) and cannot guarantee safety or durability without a backing store (Phase 2).
* **Why it cannot be implemented after Phase 4 (MCP) or Phase 5 (CLI)**: MCP tools and CLI inspection commands are merely thin protocol/UI wrappers around the runtime engine. Writing wrappers before the engine exists leads to mocking or duplicate business logic.

### Roadmap Items Covered
* [ ] Implement the workflow runtime.
* [ ] Implement `main` agent steps.
* [ ] Implement `subagent` steps.
* [ ] Implement choice results.
* [ ] Implement human gates.
* [ ] Implement workflow transitions and loops.

### Scope & Deliverables
1. **Run Lifecycle Engine**:
   * `start_run(workflow_name, task)`: Validates workflow via Phase 1, initializes persistent record in Phase 2, activates `start` step.
   * Active step inspector: Returns authoritative instructions, type, role, and inline prompt for current step.
2. **Transition & Choice Resolution**:
   * Linear step completion via `next`.
   * Choice result evaluation: strictly validates agent-reported outcome against allowed options and resolves corresponding target step.
   * Cyclic loops: allows transitions that loop back to previous steps (e.g. `changes_required -> plan`) while tracking full iteration history.
3. **Human Gate & Safety Invariants**:
   * Transitioning to a `human` step automatically pauses run (`status: paused_human`).
   * Rejects agent step completion calls when a human gate is active.
   * `resolve_human_action(run_id, action)`: Validates human action against allowed step transitions and unpauses execution.
   * Reaching an `end` step sets status to `completed`.
   * Invariant checks: ensure exactly one active step; reject arbitrary agent transitions.

### Acceptance & Verification Gate
* Comprehensive engine simulation tests:
  * Linear execution from start to end.
  * Branching execution via choices.
  * Multi-iteration review/fix loops.
  * Human gate blocking: verify agent attempts to advance fail, and only valid human action resumes the run.
  * Rejection of invalid choice values (e.g. `mostly_approved`).

---

## Phase 4: MCP Server & Tool Protocol Surface

### Purpose
Expose the Phase 3 runtime engine to coding agents via the Model Context Protocol (MCP) using stdio transport.

### Why This Phase Strictly Depends on Phase 3 & Cannot Be Reordered
* **Depends on Phase 3**: Every MCP tool maps directly to an authoritative runtime method. Without the runtime, the MCP tools have nothing to execute.
* **Why it cannot be deferred past Phase 5**: Phase 5's project initialization (`rail init`) and setup script (`setup.ps1`) configure agent instructions and registration specifically for this MCP server.
* **Why it cannot be deferred past Phase 6**: Agents cannot interact with Rail during integration tests without a functioning MCP server.

### Roadmap Items Covered
* [ ] Implement MCP server.
* [ ] Add `workflow_start`.
* [ ] Add `workflow_status`.
* [ ] Add `workflow_step`.
* [ ] Add `workflow_complete_step`.
* [ ] Add `workflow_human_action`.

### Scope & Deliverables
1. **MCP Server Protocol**:
   * JSON-RPC stdio transport compliant with official MCP specification.
2. **Tool Implementations**:
   * `workflow_start`: Accepts `workflow` and `task`, starts run, returns first step prompt.
   * `workflow_status`: Returns current step, completed steps, pending steps, and overall status.
   * `workflow_step`: Authoritative instructions and role for current active step.
   * `workflow_complete_step`: Agent reports completion (with optional choice `result`).
   * `workflow_human_action`: Resolves paused human gate with user-specified action.
3. **Protocol Guardrails**:
   * Return informative error messages when agents attempt invalid actions (e.g. trying to complete a human step or submitting an invalid choice).

### Acceptance & Verification Gate
* Protocol tests using an MCP test client verifying all 5 tools, input validation, and expected responses for both successful transitions and rejected operations.

---

## Phase 5: CLI, Project Instructions & Setup Tooling

### Purpose
Deliver operator CLI tooling, automated project instruction injection (`rail init`), and local environment setup scripts (`setup.ps1`).

### Why This Phase Strictly Depends on Phase 4 & Cannot Be Reordered
* **Depends on Phases 1–4**:
  * `rail validate` invokes the Phase 1 validator.
  * `rail workflows` discovers workflows from Phase 1.
  * `rail status` inspects Phase 2/3 active project runs.
  * `rail init` writes instructions teaching agents how to invoke the Phase 4 MCP tools.
  * `setup.ps1` configures the Phase 4 MCP server in the host system.
* **Why it cannot be implemented earlier**: You cannot configure agent instructions or generate MCP registration config before the MCP server and CLI commands are implemented and stable.

### Roadmap Items Covered
* [ ] Add `rail init`.
* [ ] Add `rail workflows`.
* [x] Add `rail validate` (CLI command).
* [ ] Add `rail status`.
* [ ] Add managed Rail blocks to `AGENTS.md` and `CLAUDE.md`.
* [ ] Add `setup.ps1` for local installation and MCP setup guidance.

### Scope & Deliverables
1. **CLI Commands (`rail`)**:
   * `rail init`: Adds or updates the marked `<!-- RAIL:START --> ... <!-- RAIL:END -->` instruction block in `AGENTS.md` and `CLAUDE.md` idempotently, preserving all surrounding content.
   * `rail workflows`: Lists available workflows in `~/.rail/workflows/` with name, version, and description.
   * `rail validate <workflow>`: CLI wrapper providing clear diagnostic output for workflow definitions.
   * `rail status`: Displays the active workflow run for the current working directory.
2. **Setup Script (`setup.ps1`)**:
   * PowerShell script that sets up global directory structure (`~/.rail/workflows`), seeds default workflows (`default.yaml`, `careful-feature.yaml`), compiles the binary, and prints ready-to-use MCP configuration blocks for major agents (Claude Code, Antigravity, OpenCode, Codex, Pi).

### Acceptance & Verification Gate
* CLI tests verifying clean execution of `rail workflows`, `rail validate`, and `rail status`.
* `rail init` idempotent editing tests: verify existing files are preserved, new files are created when absent, and repeated runs only update the delimited block.
* `setup.ps1` dry-run verification on Windows.

---

## Phase 6: Multi-Agent Integration & End-to-End Verification

### Purpose
Execute complete end-to-end coding workflows with real AI agents, verify cross-tool interoperability, and rigorously validate all 10 POC Success Criteria.

### Why This Phase Must Be Last
* This phase is the comprehensive validation gate. It requires every prior layer—validation, persistence, runtime state machine, MCP tools, CLI, and project instructions—to be 100% operational.
* Verification cannot take place in fragments; it proves the unified system operates reliably under real agent interactions.

### Roadmap Items Covered
* [ ] Test the same workflow across multiple agentic coding tools.
* [ ] Verify that agents reliably stop at human gates.
* [ ] Verify that workflow state survives session and MCP restarts.
* [ ] Complete 100% of POC Success Criteria.

### Scope & Deliverables
1. **Real-World Agent Testing**:
   * Run full tasks using `default.yaml` and `careful-feature.yaml` across supported coding agents (Claude Code, Antigravity, OpenCode, Pi).
   * Verify main agent execution and subagent delegation (`role: subagent`, `name: plan-reviewer`).
2. **Human Gate Enforcement Testing**:
   * Ensure agents halt completely at `human_review` and cannot bypass the gate until human action is submitted.
3. **Session & Process Restart Recovery**:
   * Terminate and restart agent sessions and MCP processes mid-workflow; verify `workflow_status` and `workflow_step` restore the exact active step without state drift or corruption.
4. **Final POC Sign-Off**:
   * Validate all 10 POC Success Criteria listed in the Roadmap.

### Acceptance & Verification Gate
* 100% pass on all 10 POC Success Criteria.
* Zero unhandled crashes during multi-tool test executions.
* All 24 POC roadmap items checked and completed.

---

## Roadmap Coverage Matrix (100% Complete)

| Roadmap Item | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | Phase 6 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Define and validate Workflow Language v0.1 | **✓** | | | | | |
| Load global `.yml` and `.yaml` workflows | **✓** | | | | | |
| Implement persistent workflow runs | | **✓** | | | | |
| Implement the workflow runtime | | | **✓** | | | |
| Implement `main` agent steps | | | **✓** | | | |
| Implement `subagent` steps | | | **✓** | | | |
| Implement choice results | | | **✓** | | | |
| Implement human gates | | | **✓** | | | |
| Implement workflow transitions and loops | | | **✓** | | | |
| Implement MCP server | | | | **✓** | | |
| Add `workflow_start` | | | | **✓** | | |
| Add `workflow_status` | | | | **✓** | | |
| Add `workflow_step` | | | | **✓** | | |
| Add `workflow_complete_step` | | | | **✓** | | |
| Add `workflow_human_action` | | | | **✓** | | |
| Add `rail init` | | | | | **✓** | |
| Add `rail workflows` | | | | | **✓** | |
| Add `rail validate` | **✓** (engine) | | | | **✓** (cli) | |
| Add `rail status` | | | | | **✓** | |
| Add managed Rail blocks to `AGENTS.md` and `CLAUDE.md` | | | | | **✓** | |
| Add `setup.ps1` for local installation and MCP setup guidance | | | | | **✓** | |
| Test the same workflow across multiple agentic coding tools | | | | | | **✓** |
| Verify that agents reliably stop at human gates | | | | | | **✓** |
| Verify that workflow state survives session and MCP restarts | | | | | | **✓** |
| **All 10 POC Success Criteria Met** | | | | | | **100%** |

---

# Non-Goals

Rail is not intended to:

* replace coding agents;
* replace MCP;
* replace Git;
* replace GitHub;
* replace CI;
* become another IDE;
* prescribe one universal software-development process;
* automatically decide how every engineering task should be performed;
* solve model reasoning limitations;
* make unreliable models inherently reliable.

Rail controls **process execution**.

The coding agent remains responsible for performing the engineering work inside each step.

---

# Current Status

Phase 1 (**Workflow Specification, Loader & Static Validator**) has been implemented and fully verified with 78 unit tests and 100% validator test coverage.

Phase 2 (**Persistence Layer & Durable State Store**) has been implemented and fully verified with 28 storage tests and 100% storage test coverage, including the process crash and exact state recovery acceptance gate.

Phase 3 (**Workflow Runtime & Transition State Machine**) has been implemented and fully verified with 27 runtime simulation tests covering linear flows, choice branching, review/fix cyclic loops, strict human gate blocking, and state durability.

Phase 4 (**MCP Server & Tool Protocol Surface**) is next.

---

# Summary

Rail turns engineering workflows from informal instructions into executable process state.

Instead of relying on a coding agent to remember:

```text
plan first
review the plan
implement
verify
wait for me
then continue
```

the process becomes:

```text
User-defined YAML
       ↓
      Rail
       ↓
Authoritative current step
       ↓
   Coding Agent
       ↓
Reported result
       ↓
Rail-controlled transition
```

The goal is not to reduce the coding agent's capability.

The goal is to give the user control over **how that capability is exercised**.

**Rail — keep coding agents on the rails.**
