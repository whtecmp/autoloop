---
name: kanboard-autoloop-orchestrator
description: Use ONLY when running the Kanboard autoloop router that handles one yellow task at a time through the matching column-handler skill.
---

# Kanboard Autoloop Orchestrator

Route and handle eligible Kanboard tasks one at a time. Do not spawn subagents or child `opencode run` processes.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
qa_duration: <optional QA duration such as 10s, 5m, or 3h>
ticket_lock_url: <optional ticket lock server URL>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
```

Defaults for color-capable handlers:

```text
kanboard_url: http://172.17.0.1:8080/
kanboard_username: admin
kanboard_token_path: /token
ticket_lock_url: http://172.17.0.1:8000/
```

Pass `kanboard_url` through as the base URL. Color changes must be done by running `/root/.config/opencode/scripts/color-change.py`.

Color-change command pattern:

```bash
/root/.config/opencode/scripts/color-change.py "<project_name>" <task_id> <red|yellow|green> --kanboard-url "<kanboard_url>" --username "<kanboard_username>" --token-path "<kanboard_token_path>"
```

If `qa_duration` is missing, use `10m`. Pass `qa_duration` through only when using `qa-column-handler`. Valid duration format is a positive integer followed immediately by `s`, `m`, or `h`, such as `10s`, `5m`, or `3h`.

If `ticket_lock_url` is missing, use `http://172.17.0.1:8000/`.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_projects, kanboard_get_columns, kanboard_get_tasks, kanboard_add_task_comment
bash
read
skill
```

Tool usage rules:

1. Use `kanboard_get_projects`, `kanboard_get_columns`, and `kanboard_get_tasks` for all Kanboard project, column, and task lookup.
2. Use `kanboard_add_task_comment` only when the orchestrator itself must comment on a source-refresh failure before stopping.
3. Use `bash` for git commands, the ticket lock `curl` request, directory creation, and `/root/.config/opencode/scripts/color-change.py`.
4. Use `read` only to inspect local directory presence or simple local files when needed.
5. Use `skill` to load the matching handler skill inline. Do not invent or call a nonexistent subagent tool.
6. Do not use edit/write tools from the orchestrator. The orchestrator must not create plans or modify application code.

## Required Validation

1. Resolve the Kanboard project with `kanboard_get_projects` using an exact `project_name` match.
2. Fetch project columns with `kanboard_get_columns`.
3. Validate that `Backlog`, `To Do`, `Plan`, `WIP`, `Merging`, `QA`, and `Done` each exist exactly once.
4. If any required column is missing or duplicated, stop and report the issue. Do not process tasks.
5. Identify column IDs for `To Do`, `Plan`, `WIP`, `Merging`, `QA`, and `Done`.

## Workspace Setup

The current working directory must contain two primary directories:

```text
plans
src
```

Ensure both exist. Ensure each is a separate local git repository. If either directory does not contain `.git`, initialize it with a `dev` branch.

Use minimal safe commands such as:

```bash
git init -b dev
```

If `git init -b dev` is unsupported, initialize the repository and rename the current branch to `dev`.

## Routing Rules

Fetch active tasks for the project with `kanboard_get_tasks`. Ignore `Backlog` completely. Ignore `Done`. Only process tasks whose `color_id` is exactly `yellow`. Never process `red` or `green` tasks.

Route yellow tasks by current column:

```text
To Do -> to-do-column-handler
Plan  -> plan-column-handler
WIP   -> wip-column-handler
Merging -> merging-column-handler
QA    -> qa-column-handler
```

## Ticket Lock Check

Before starting work on any eligible yellow task, ask the ticket lock server whether that project/task/column combination is already taken. This check must happen before source refresh, before color changes, and before loading the handler skill.

Send the exact project name, task ID, and current column title using the field names from the server contract:

```bash
curl -sS "<ticket_lock_url>" \
  -H "Content-Type: application/json" \
  -d '{"requested-ticket-id":"<task_id>","current-column":"<column_title>","project-name":"<project_name>"}'
```

The server response is plain text:

```text
ok
taken
```

Rules:

1. If the response is exactly `taken`, skip that task and continue scanning for the next eligible yellow task. Do not change the task color, do not add comments, do not refresh `src`, and do not run a handler.
2. If the response is exactly `ok`, proceed with the source refresh and handler workflow for that task.
3. If the lock request fails or returns anything other than `ok` or `taken`, stop the orchestrator run and report the lock-check failure. Do not change the task color or add task comments, because another worker may already be handling it.

## Source Refresh Before Work

Before starting any yellow task, update `src` from the git server and ensure it is on the latest `dev` branch.

Required source refresh workflow after selecting an eligible yellow task and before loading its handler:

1. Confirm `src/` exists and is a git repository.
2. In `src/`, inspect `git status --short`.
3. If `src/` has uncommitted changes, run `/root/.config/opencode/scripts/color-change.py` to mark the selected task `red`, add a task comment explaining that `src` is dirty and cannot be safely refreshed, do not run the handler, and stop the entire orchestrator run.
4. Run `git fetch --all --prune` in `src/`.
5. Check out `dev` in `src/`. If local `dev` does not exist but `origin/dev` does, create local `dev` tracking `origin/dev`.
6. Run `git pull --ff-only origin dev` in `src/`.
7. If any git command fails, run `/root/.config/opencode/scripts/color-change.py` to mark the selected task `red`, add a task comment with the failing command and error summary, do not run the handler, and stop the entire orchestrator run.

Do not start a handler until this source refresh succeeds. Treat any source refresh failure as a broader repository synchronization problem. After marking/commenting the selected task red, end the orchestrator run instead of processing more tickets.

## Sequential Loop

Process at most one task at a time in the current orchestrator session.

Each loop iteration:

1. Fetch active tasks for the project.
2. Ignore tasks in `Backlog` and `Done`.
3. Scan eligible tasks whose `color_id` is exactly `yellow` and whose column routes to a handler.
4. For each eligible task in scan order, call the ticket lock server with the exact project name, task ID, and current column title.
5. Skip tasks whose lock response is `taken` without changing Kanboard state.
6. Select the first eligible task whose lock response is `ok`.
7. If no eligible task has an `ok` lock response, report that no available unlocked work exists and stop. Do not sleep or busy-loop.
8. Refresh `src` from the latest `dev` branch as described above.
9. Load and follow the matching handler skill inline in the current session.
10. Pass through `project_name`, `task_id`, `kanboard_url`, `kanboard_username`, and `kanboard_token_path`.
11. For QA tasks, also pass `qa_duration`.
12. The handler must run `/root/.config/opencode/scripts/color-change.py` for every task color change.
13. After the handler finishes, immediately re-poll and start the next loop iteration.

The orchestrator itself must not implement ticket work outside the loaded handler skill. It may perform validation, workspace setup, routing, and loop control only.

## Handler Prompt Pattern

When using a handler skill inline, carry these inputs into the handler workflow:

```text
project_name: <project_name>
task_id: <task_id>
kanboard_url: <kanboard_url>
kanboard_username: <kanboard_username>
kanboard_token_path: <kanboard_token_path>
qa_duration: <qa_duration or 10m, only for QA>
```

For every color change, run `/root/.config/opencode/scripts/color-change.py`. Do not change task colors directly with MCP from the orchestrator.

## Usage Example

For sandbox testing, start headless opencode with this skill requested and a prompt like:

```text
Use the kanboard-autoloop-orchestrator skill.

project_name: TestProj1
qa_duration: 10s
kanboard_url: http://172.17.0.1:8080/
kanboard_username: admin
kanboard_token_path: /token
ticket_lock_url: http://172.17.0.1:8000/

Route eligible yellow tasks only. Handle one task at a time. Do not spawn subagents or child opencode processes.
```

## Completion Rules

Report which tasks were ignored, handled, moved, completed, or blocked. Do not spawn subagents. Do not launch child `opencode run` processes. Do not use local PID registries or concurrency counters.
