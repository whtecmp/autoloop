---
name: wip-column-handler
description: Use ONLY when handling a yellow Kanboard task in the WIP column by implementing from a referenced plan.
---

# WIP Column Handler

Implement the ticket from its plan in the current implementation directory and fill the pre-created output JSON. Do not change Kanboard task state. Only edit source/test files and run verification; the orchestrator handles all workflow finalization after this skill finishes.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
workspace: <workspace root containing plans/ and src/>
implementation_dir: <current implementation directory, usually src-<task_id>>
plan_file: <absolute plan file path resolved by the orchestrator>
output_json: <absolute path to output-<task_id>.json>
```

The orchestrator pre-creates the output file at the exact absolute path provided as `output_json` and runs this skill with the current working directory set to `src-<task_id>`. You MUST fill that exact file. Do not write `/output-<task_id>.json`, do not write a relative `output-<task_id>.json`, and do not create any other output JSON file.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_task_details, kanboard_get_task_comments
bash
read, glob, grep
write/edit tools
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket state and implementation context.
2. Use `read` to read the plan file and local files/directories. Use `glob` to locate code files by pattern. Use `grep` to search code.
3. Use write/edit tools for source-code and test changes inside the current implementation directory and to fill the exact absolute `output_json` path.
4. Use `bash` only for tests, builds, lint, app runs, and manual checks. Do not use it for repository state-management work.
5. Do not move the Kanboard task, change its color, or add Kanboard comments directly.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Read the plan from the absolute `plan_file` path provided by the orchestrator.
4. Confirm the plan is specific enough to implement.
5. Implement the feature in the current implementation directory, not in `src/`.
6. Add or update unit tests when applicable.
7. Run relevant tests, build, lint, and manual checks from the current implementation directory.
8. Remove temporary test files, logs, scratch files, generated debug artifacts, local app output, and any dirty files unrelated to the actual source/test changes before reporting success.
9. If blocked, write failure output with specific comments explaining the issue.
10. If successful, write success output with implementation summary, deviations from the plan, and tests run.

## Implementation Rules

Follow the plan, but adapt if the codebase requires it. Keep changes minimal and avoid over-engineering. Mention meaningful deviations from the plan in the output comments.

Never implement directly in the shared `src/` directory. The orchestrator runs this skill inside the isolated implementation directory.

## Output JSON

Fill the pre-created file at the exact absolute `output_json` path with this exact JSON shape before reporting completion:

```json
{
  "task_id": 123,
  "status": "success",
  "comments": [
    "Implemented the requested behavior. Tests run: npm test."
  ]
}
```

Failure output MUST use `status: "failure"` and MUST include at least one useful string in `comments`.

Required fields:

1. `task_id`: integer matching the input task id.
2. `status`: exactly `success` or `failure`.
3. `comments`: array of strings for the orchestrator to add to the Kanboard ticket. If `status` is `failure`, this array MUST contain at least one useful error comment.

## Completion Rules

Never report completion until the exact absolute `output_json` path contains valid JSON matching the contract. Before success, clean any test output, logs, scratch files, temporary files, generated debug files, or unrelated dirty files. The orchestrator, not this skill, will finalize the file changes, post comments, change color, and advance the ticket.
