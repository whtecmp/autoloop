---
name: plan-column-handler
description: Use ONLY when handling a yellow Kanboard task in the Plan column by creating a markdown implementation plan.
---

# Plan Column Handler

Analyze the repository and ticket, write one detailed markdown implementation plan under `plans/`, and fill the pre-created output JSON. Do not change Kanboard task state. Only create the plan content and output JSON; the orchestrator handles all workflow finalization after this skill finishes.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
workspace: <workspace root containing plans/ and src/>
output_json: <absolute path to output-<task_id>.json>
```

The orchestrator pre-creates `output-<task_id>.json` in the workspace root. Fill that file with the final JSON result.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_task_details, kanboard_get_task_comments
read, glob, grep
write/edit tools
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket requirements and existing context.
2. Use `read`, `glob`, and `grep` to analyze `src/` and existing `plans/`.
3. Use write/edit tools to create or update the markdown plan file under `plans/` and to fill `output-<task_id>.json`.
4. Do not move the Kanboard task, change its color, or add Kanboard comments directly.
5. Do not run workflow finalization commands. The orchestrator owns finalizing and publishing the result.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Analyze the repository and ticket requirements.
4. Write one detailed markdown plan file inside `plans/`.
5. Remove any temporary notes, scratch files, logs, generated debug artifacts, or unrelated dirty files before reporting success.
6. If planning is blocked, write `status: "failure"` to `output-<task_id>.json` with specific comments explaining the issue.
7. If planning succeeds and the plan file exists, write `status: "success"` to `output-<task_id>.json`. Include a comment using the exact format `PLAN_FILE: <path>`.

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

Plans should be specific enough for the WIP handler to implement without re-deciding the scope. Note meaningful ambiguity in `Risks / Open Questions`; if ambiguity blocks implementation, write failure output instead of a speculative plan.

## Output JSON

Fill the pre-created `output-<task_id>.json` with this exact JSON shape before reporting completion:

```json
{
  "task_id": 123,
  "status": "success",
  "comments": [
    "PLAN_FILE: plans/kanboard-task-123-example.md",
    "Plan file is ready."
  ]
}
```

Failure output MUST use `status: "failure"` and MUST include at least one useful string in `comments`.

Required fields:

1. `task_id`: integer matching the input task id.
2. `status`: exactly `success` or `failure`.
3. `comments`: array of strings for the orchestrator to add to the Kanboard ticket. If `status` is `failure`, this array MUST contain at least one useful error comment.

## Completion Rules

Never report completion until `output-<task_id>.json` contains valid JSON matching the contract. Before success, clean any test output, logs, scratch files, temporary files, or unrelated dirty files. The orchestrator, not this skill, will finalize the file changes, post comments, change color, and advance the ticket.
