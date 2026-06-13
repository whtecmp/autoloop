---
name: qa-column-handler
description: Use ONLY when handling a yellow Kanboard task in the QA column by thoroughly verifying work after it has been merged to dev.
---

# QA Column Handler

Verify work that has been merged to `dev` in an isolated `qa-<task_id>` copy for the configured QA duration, then write a structured result. Do not change Kanboard task state. The orchestrator handles colors, comments, and final advancement after reading your output JSON.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
qa_duration: <optional QA duration such as 10s, 5m, or 3h>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
workspace: <workspace root>
qa_dir: <current QA directory, usually qa-<task_id>>
plan_file: <absolute plan file path resolved by the orchestrator>
output_json: <absolute path to output-<task_id>.json>
```

The orchestrator pre-creates `output-<task_id>.json` in the workspace root and runs this skill with the current working directory set to `qa-<task_id>`. Fill that file with the final JSON result.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_task_details, kanboard_get_task_comments
bash
read, glob, grep
write/edit tools, only inside `qa-<task_id>` for testing purposes and for the workspace-root `output-<task_id>.json`
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket state, WIP comments, Merging comments, branch name, and pushed `dev` commit hash.
2. Use `read`, `glob`, and `grep` to inspect code and tests.
3. Use `bash` to run tests/build/lint/manual checks and check date/time during QA batches. Do not create, remove, or copy the `qa-<task_id>` directory; the orchestrator owns that setup and cleanup.
4. Use write/edit tools only inside `qa-<task_id>` for testing purposes and to fill the workspace-root `output-<task_id>.json`. Writing the output JSON outside `qa-<task_id>` is explicitly allowed and required.
5. Do not move the Kanboard task, change its color, or add Kanboard comments directly.

If `qa_duration` is missing, use `10m`.

Validate `qa_duration` before starting QA. The only valid format is a positive integer followed immediately by one unit: `s` for seconds, `m` for minutes, or `h` for hours. Examples: `10s`, `5m`, `3h`. Reject zero, negative values, decimals, spaces, and unknown units.

Convert the duration to elapsed seconds for the QA loop:

```text
<N>s = N seconds
<N>m = N * 60 seconds
<N>h = N * 3600 seconds
```

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Validate and parse `qa_duration`, using `10m` if it was not provided.
4. Review the WIP and Merging summary comments, branch name, pushed `dev` commit hash, the provided `plan_file`, and relevant implementation/merge diff.
5. Confirm the current working directory is the orchestrator-created `qa-<task_id>` copy.
6. Run all QA commands, manual checks, automated tests, app runs, and inspections from `qa-<task_id>`, not from shared `src`.
7. Run repeated batches of manual and automated verification.
8. Check current date/time after every batch.
9. Continue until at least the configured `qa_duration` has elapsed. Spend the full configured time testing thoroughly in headless mode as much as the environment allows.
10. If issues are found, write failure output with detailed reproduction steps, observed failures, commands run, expected behavior, observed behavior, and relevant file paths.
11. If no issues are found, write success output summarizing QA coverage.

## QA Batch Examples

Use the checks that fit the codebase and ticket:

```text
Run unit tests
Run integration tests if available
Run app locally if feasible
Exercise CLI/API/UI flows related to the ticket
Check edge cases
Check regressions around nearby behavior
Review implementation diff against the plan
Check docs or config changes if relevant
```

## Output JSON

Fill the pre-created `output-<task_id>.json` with this exact JSON shape before reporting completion:

```json
{
  "task_id": 123,
  "status": "success",
  "comments": ["QA passed after 10s. Coverage: npm test and manual CLI smoke check."]
}
```

Failure output MUST use `status: "failure"` and MUST include at least one useful string in `comments`.

Required fields:

1. `task_id`: integer matching the input task id.
2. `status`: exactly `success` or `failure`.
3. `comments`: array of strings for the orchestrator to add to the Kanboard ticket. If `status` is `failure`, this array MUST contain at least one useful error comment.

## Completion Rules

Never report completion until `output-<task_id>.json` contains valid JSON matching the contract. The orchestrator, not this skill, will post comments, change color, and advance the ticket.
