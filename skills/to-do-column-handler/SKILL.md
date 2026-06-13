---
name: to-do-column-handler
description: Use ONLY when evaluating a yellow Kanboard task in the To Do column for the autoloop workflow.
---

# To Do Column Handler

Evaluate whether a To Do task is actionable. Do not change Kanboard task state. The orchestrator handles colors, comments, and column advancement after reading your output JSON.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
workspace: <workspace root>
output_json: <absolute path to output-<task_id>.json>
```

The orchestrator pre-creates `output-<task_id>.json` in the workspace root. Fill that file with the final JSON result.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_task_details, kanboard_get_task_comments
write/edit tools only for `output-<task_id>.json`
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect the ticket.
2. Use write/edit tools only to fill the required JSON result into `output-<task_id>.json`.
3. Do not move the Kanboard task, change its color, or add Kanboard comments directly.
4. Do not write plans, change application code, run implementation, or run QA.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Read the task title, description, and relevant comments.
4. Decide whether the ticket is actionable.
5. If the ticket is actionable, write `status: "success"` to `output-<task_id>.json` with comments explaining it is ready for planning.
6. If the ticket is unclear, write `status: "failure"` to `output-<task_id>.json` with concrete clarification questions in `comments`.

## Actionability Standard

A ticket is actionable when the implementer can determine the requested behavior, scope, likely target area, and success criteria from the task and comments.

Questions must be specific and actionable. Do not ask generic questions like "Can you clarify?". Ask for the missing decision, input, environment, expected behavior, or acceptance criterion.

## Output JSON

Fill the pre-created `output-<task_id>.json` with this exact JSON shape before reporting completion:

```json
{
  "task_id": 123,
  "status": "success",
  "comments": ["Ready for planning: scope and success criteria are clear."]
}
```

Failure output MUST use `status: "failure"` and MUST include at least one useful string in `comments`.

Required fields:

1. `task_id`: integer matching the input task id.
2. `status`: exactly `success` or `failure`.
3. `comments`: array of strings for the orchestrator to add to the Kanboard ticket. If `status` is `failure`, this array MUST contain at least one useful error or clarification comment.

## Completion Rules

Never report completion until `output-<task_id>.json` contains valid JSON matching the contract. The orchestrator, not this skill, will post comments, change color, and advance the ticket.
