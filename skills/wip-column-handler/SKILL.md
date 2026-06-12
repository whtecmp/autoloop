---
name: wip-column-handler
description: Use ONLY when handling a yellow Kanboard task in the WIP column by implementing from a referenced plan, pushing the implementation branch, and routing to Merging.
---

# WIP Column Handler

Implement the ticket from its plan in an isolated `src-<task_id>` working directory, push the implementation branch, then move the task to Merging.

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

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket state and find `PLAN_FILE: <path>`.
2. Use `read` to read the plan file and local files/directories. Use `glob` to locate code files by pattern. Use `grep` to search code.
3. Use write/edit tools for source-code and test changes inside `src-<task_id>`.
4. Use `bash` for git commands, copying/removing working directories, running tests/build/lint/manual checks, pushing the implementation branch, and running `/root/.config/opencode/scripts/color-change.py`.
5. Use `kanboard_get_projects`, `kanboard_get_columns`, and `kanboard_move_task` to route successful work to `Merging`.
6. Use `kanboard_add_task_comment` for implementation summaries, `BRANCH_NAME: <branch>`, blockers, push failures, and cleanup failures.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Run `/root/.config/opencode/scripts/color-change.py` to mark the task `green`.
4. Refresh the separate `plans/` git repository from the `dev` branch before reading any plan file: confirm `plans/` exists and is a git repository, run `git fetch --all --prune`, check out `dev` (creating local `dev` tracking `origin/dev` if needed), and run `git pull --ff-only origin dev`.
5. If the `plans/` refresh fails, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment with the failing git command and error summary, and leave it in `WIP`.
6. Find the referenced plan file path from the latest task comment containing `PLAN_FILE: <path>`.
7. Read the plan.
8. Confirm `src/` exists and is a local git repository.
9. Create a sibling working directory named `src-<task_id>` next to `src` and `plans`.
10. If `src-<task_id>` already exists, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment explaining the existing-directory collision, and leave it in `WIP`.
11. Copy the current `src` content into `src-<task_id>`.
12. In `src-<task_id>`, create a new git branch with an indicative name such as `task-<task_id>-<slug>`.
13. Implement the feature in `src-<task_id>`, not in `src`.
14. Add or update unit tests when applicable.
15. Run relevant tests, build, lint, and manual checks from `src-<task_id>`.
16. Commit the implementation locally in the `src-<task_id>` repository.
17. Push the implementation branch to the git server with `git push -u origin <branch>`.
18. If the push fails, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment with the push error summary, and leave it in `WIP`.
19. If blocked for any other reason, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment explaining the issue, and leave it in `WIP`.
20. If successful, resolve the project by exact name with `kanboard_get_projects`, fetch columns with `kanboard_get_columns`, confirm `Merging` exists exactly once, add a comment summarizing implementation, deviations from the plan, commit hash, tests run, and branch name using the exact format `BRANCH_NAME: <branch>`; move the task to `Merging`; run `/root/.config/opencode/scripts/color-change.py` to mark it `yellow`; then remove the `src-<task_id>` working directory.

## Implementation Rules

Follow the plan, but adapt if the codebase requires it. Keep changes minimal and avoid over-engineering. Mention meaningful deviations from the plan in the task comment.

Never implement directly in `src`. Always use the isolated `src-<task_id>` directory and branch, even though the current orchestrator handles only one task at a time.

## Copy Rules

The copy should preserve the source repository contents, including `.git`, so the isolated directory has its own local git history and branch. The implementation branch must be pushed to the configured remote before the task moves to `Merging`.

## Git Rules

Commit only inside `src-<task_id>`. Stage only files changed for the current task. Use a concise commit message tied to the Kanboard task.

Before pushing, inspect `git status`, `git diff`, `git log --oneline -5`, current branch name, and configured remotes. Do not push secrets or unrelated changes.

Push only the implementation branch from the WIP handler. Do not push `dev` from WIP; merging and pushing `dev` belongs to `merging-column-handler`.

After the implementation branch has been pushed, the task has been moved to `Merging`, and the final yellow color has been verified, remove the `src-<task_id>` working directory. If cleanup fails after the task has already been moved and marked yellow, add a Kanboard comment with the cleanup issue but do not move the task back.

## Failure Handling

If refreshing `plans/` from `dev` fails, the plan file is missing, `src/` is missing or not a git repository, `src-<task_id>` already exists, tests cannot be run for a blocking reason, implementation is blocked, commit fails, branch push fails, the `Merging` column cannot be resolved exactly once, or a required color change fails, mark the task red when possible and comment with the specific issue. Do not move the task after a failed required color change.

## Completion Rules

Do not merge to `dev` and do not run final QA beyond implementation verification. Do not change task colors with MCP; every color change must use `/root/.config/opencode/scripts/color-change.py`.
