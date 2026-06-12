---
name: to-do-column-handler
description: Use ONLY when handling a yellow Kanboard task in the To Do column for the autoloop workflow.
---

# To Do Column Handler

Evaluate whether a To Do task is actionable, then either request clarification or move it to planning.

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
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect the ticket.
2. Use `bash` to run `/root/.config/opencode/scripts/color-change.py` for every color change.
3. Use `kanboard_get_projects` and `kanboard_get_columns` before moving the task, so the `Plan` column is resolved exactly once.
4. Use `kanboard_move_task` to move clear tickets to `Plan`.
5. Use `kanboard_add_task_comment` for clarification questions or ready-for-planning comments.
6. Do not use edit/write tools. The To Do handler must not write plan files or code.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Run `/root/.config/opencode/scripts/color-change.py` to mark the task `green`.
4. Read the task title, description, and relevant comments.
5. Decide whether the ticket is actionable.
6. If the ticket is unclear, run `/root/.config/opencode/scripts/color-change.py` to mark it `red`, add a comment with concrete questions, and leave it in `To Do`.
7. If the ticket is clear, resolve the project by exact name with `kanboard_get_projects`, fetch columns with `kanboard_get_columns`, confirm `Plan` exists exactly once, move it to `Plan` with `kanboard_move_task`, run `/root/.config/opencode/scripts/color-change.py` to mark it `yellow`, and add a short comment saying it is ready for planning.

## Actionability Standard

A ticket is actionable when the implementer can determine the requested behavior, scope, likely target area, and success criteria from the task and comments.

Questions must be specific and actionable. Do not ask generic questions like "Can you clarify?". Ask for the missing decision, input, environment, expected behavior, or acceptance criterion.

## Failure Handling

If fetching task details/comments fails, if the task is not in the expected project, if the `Plan` column cannot be resolved exactly once, or if a required color change fails, stop and report the failure. Do not move the task after a failed required color change.

## Completion Rules

Do not write plans, change application code, run implementation, or run QA. Do not change task colors with MCP; every color change must use `/root/.config/opencode/scripts/color-change.py`.
