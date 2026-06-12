---
name: qa-column-handler
description: Use ONLY when handling a yellow Kanboard task in the QA column by thoroughly verifying work after it has been merged to dev.
---

# QA Column Handler

Verify work that has been merged to `dev` in an isolated `qa-<task_id>` copy for the configured QA duration, then either report issues or move the task to Done.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
qa_duration: <optional QA duration such as 10s, 5m, or 3h>
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
write/edit tools, only inside `qa-<task_id>` for testing purposes
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket state, WIP comments, Merging comments, branch name, and pushed `dev` commit hash.
2. Use `read` to inspect local files and directories. Use `glob` to find files by path pattern. Use `grep` to search code and tests.
3. Use `bash` to create/remove/copy `qa-<task_id>`, run tests/build/lint/manual checks, check date/time during QA batches, and run `/root/.config/opencode/scripts/color-change.py`.
4. Use `kanboard_get_projects`, `kanboard_get_columns`, and `kanboard_move_task` to move successful QA tasks to `Done`.
5. Use `kanboard_add_task_comment` for QA start, QA coverage summary, reproduction steps, failures, and blockers.
6. Use write/edit tools only inside `qa-<task_id>` and only when needed for testing, such as creating temporary test fixtures, scratch files, small QA-only scripts, or test harness files. Do not edit `src`, `plans`, `merging-<task_id>`, or implementation files outside `qa-<task_id>`.

If `qa_duration` is missing, use `10m`.

Validate `qa_duration` before marking the task green. The only valid format is a positive integer followed immediately by one unit: `s` for seconds, `m` for minutes, or `h` for hours. Examples: `10s`, `5m`, `3h`. Reject zero, negative values, decimals, spaces, and unknown units.

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
4. Run `/root/.config/opencode/scripts/color-change.py` to mark the task `green`.
5. Add a comment with the QA start date/time and configured `qa_duration`.
6. Review the WIP and Merging summary comments, branch name, pushed `dev` commit hash, plan file, and relevant implementation/merge diff.
7. Confirm `src/` exists and is on the up-to-date merged `dev` code.
8. Create a sibling working directory named `qa-<task_id>` next to `src`, `plans`, and any prior working directories.
9. If `qa-<task_id>` already exists, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment explaining the existing-directory collision, and leave it in `QA`.
10. Copy the current `src` content into `qa-<task_id>`.
11. Run all QA commands, manual checks, automated tests, app runs, and inspections from `qa-<task_id>`, not from `src`.
12. Run repeated batches of manual and automated verification.
13. Check current date/time after every batch.
14. Continue until at least the configured `qa_duration` has elapsed. Spend the full configured time testing thoroughly in headless mode as much as the environment allows.
15. If issues are found, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add detailed reproduction steps and observed failures, and leave it in `QA`.
16. If no issues are found, resolve the project by exact name with `kanboard_get_projects`, fetch columns with `kanboard_get_columns`, confirm `Done` exists exactly once, add a comment summarizing QA coverage, move the task to `Done` with `kanboard_move_task`, and run `/root/.config/opencode/scripts/color-change.py` to mark it `yellow`.

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

## Failure Handling

If `qa_duration` is invalid, do not start QA and do not mark the task green. Report the invalid value to the caller and add a task comment asking for a valid duration if possible.

If `src/` is missing, `qa-<task_id>` already exists, copying `src` into `qa-<task_id>` fails, the merged implementation cannot be located, the plan reference is missing, tests reveal failures, manual verification finds a regression, the `Done` column cannot be resolved exactly once, or a required color change fails, do not move the task to Done. Mark it red when possible and comment with specific reproduction steps, commands run, expected behavior, observed behavior, and relevant file paths.

## Completion Rules

Do not implement new feature work during QA except for harmless investigation. Do not push. Do not run QA commands directly in `src`; use `qa-<task_id>`. Write/edit is allowed only inside `qa-<task_id>` for testing purposes. Do not change task colors with MCP; every color change must use `/root/.config/opencode/scripts/color-change.py`.
