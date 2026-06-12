---
name: plan-column-handler
description: Use ONLY when handling a yellow Kanboard task in the Plan column by creating, committing, and pushing a markdown implementation plan.
---

# Plan Column Handler

Analyze the repository and ticket, write a detailed plan in the separate `plans` git repository, commit it, push `dev`, then move the task to WIP.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
```

Use `/root/.config/opencode/scripts/color-change.py` for every task color change. Do not use a color-change skill.

Command pattern:

```bash
/root/.config/opencode/scripts/color-change.py "<project_name>" <task_id> <red|yellow|green> --kanboard-url "<kanboard_url>" --username "<kanboard_username>" --token-path "<kanboard_token_path>"
```

Pass `kanboard_url` as the Kanboard base URL, for example `http://172.17.0.1:8080/`.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_task_details, kanboard_get_task_comments, kanboard_get_projects, kanboard_get_columns, kanboard_move_task, kanboard_add_task_comment
bash
read, glob, grep
write/edit tools
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket requirements and existing context.
2. Use `read` to read local files and directories. Use `glob` to find files by path pattern. Use `grep` to search repository content.
3. Use write/edit tools to create or update the markdown plan file under `plans/`.
4. Use `bash` for git commands in `plans/`, including fetch, checkout, pull, commit, and `git push origin dev`.
5. Use `bash` to run `/root/.config/opencode/scripts/color-change.py` for every color change.
6. Use `kanboard_get_projects`, `kanboard_get_columns`, and `kanboard_move_task` to route successful plans to `WIP`.
7. Use `kanboard_add_task_comment` for `PLAN_FILE: <path>` and blocker comments.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Run `/root/.config/opencode/scripts/color-change.py` to mark the task `green`.
4. Analyze the repository and ticket requirements.
5. Ensure `plans/` exists in the current working directory and is a separate local git repository with a configured remote.
6. In `plans/`, run `git fetch --all --prune`.
7. Check out `dev` in `plans/`. If local `dev` does not exist but `origin/dev` does, create local `dev` tracking `origin/dev`.
8. Run `git pull --ff-only origin dev` in `plans/`.
9. Use write/edit tools to write one detailed markdown plan file inside `plans/`.
10. Commit the plan file locally in the `plans` repository.
11. Push only the `dev` branch in the `plans` repository with `git push origin dev`.
12. If planning is blocked, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment explaining the complication, and leave it in `Plan`.
13. If the plan commit or `git push origin dev` fails, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment with the git error summary, and leave it in `Plan`.
14. If planning succeeds and the plan was pushed to `dev`, resolve the project by exact name with `kanboard_get_projects`, fetch columns with `kanboard_get_columns`, confirm `WIP` exists exactly once, add a task comment using the exact format `PLAN_FILE: <path>`, move the task to `WIP` with `kanboard_move_task`, and run `/root/.config/opencode/scripts/color-change.py` to mark it `yellow`.

## Plan File

Use this naming pattern when practical:

```text
plans/kanboard-task-<task_id>-<slug>.md
```

The plan must include these sections:

```markdown
# Task <id>: <title>

## Summary

## Requirements

## Affected Files

## Implementation Steps

## Testing Plan

## Risks / Open Questions

## Completion Criteria
```

Plans should be specific enough for the WIP handler to implement without re-deciding the scope. Note meaningful ambiguity in `Risks / Open Questions`; if ambiguity blocks implementation, mark the task red instead of writing a speculative plan.

## Git Rules

Only commit inside the `plans` repository. The `plans` repository is separate from `src`. Stage only the plan file for the current task. Use a concise commit message such as:

```text
Add plan for Kanboard task <task_id>
```

Push only the `dev` branch in the `plans` repository. Do not push any other branch. Do not commit unrelated files.

## Failure Handling

If a required color change fails, stop and report the failure. Do not move the task after a failed required color change. If git setup, commit, pull, or push fails, or if the `WIP` column cannot be resolved exactly once, mark the task red and comment with the specific issue.

## Completion Rules

Do not implement source changes or run QA. Do not change task colors with MCP; every color change must use `/root/.config/opencode/scripts/color-change.py`.
