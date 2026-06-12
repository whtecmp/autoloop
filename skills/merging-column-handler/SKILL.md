---
name: merging-column-handler
description: Use ONLY when handling a yellow Kanboard task in the Merging column by merging its implementation branch into dev, testing, pushing dev, and routing to QA.
---

# Merging Column Handler

Merge the ticket implementation branch into `dev`, verify the merged result, push `dev`, then move the task to QA.

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
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` to inspect ticket state and find `BRANCH_NAME: <branch>`.
2. Use `read` to inspect local directories/files if needed. Use `glob` and `grep` to locate and inspect relevant files during merge verification.
3. Use `bash` for copying/removing `merging-<task_id>`, all git commands, running tests/build/lint/manual checks, pushing `dev`, and running `/root/.config/opencode/scripts/color-change.py`.
4. Use `kanboard_get_projects`, `kanboard_get_columns`, and `kanboard_move_task` to route successful merges to `QA`.
5. Use `kanboard_add_task_comment` for merge summaries, blockers, test failures, push failures, and cleanup failures.
6. Do not use edit/write tools for feature implementation. If the merge requires code changes beyond conflict resolution, mark the task red.

## Required Workflow

1. Fetch task details with `kanboard_get_task_details`.
2. Fetch task comments with `kanboard_get_task_comments`.
3. Run `/root/.config/opencode/scripts/color-change.py` to mark the task `green`.
4. Find the latest task comment containing `BRANCH_NAME: <branch>`.
5. If no branch name is found, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment explaining that no implementation branch was found, and leave it in `Merging`.
6. Confirm `src/` exists and is a local git repository with a configured remote that can be fetched.
7. Create a sibling working directory named `merging-<task_id>` next to `src` and `plans`.
8. If `merging-<task_id>` already exists, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment explaining the existing-directory collision, and leave it in `Merging`.
9. Copy the current `src` content into `merging-<task_id>`.
10. In `merging-<task_id>`, run `git fetch --all --prune`.
11. Check out `dev`. If local `dev` does not exist but `origin/dev` does, create local `dev` tracking `origin/dev`.
12. Run `git pull --ff-only origin dev`.
13. Merge the implementation branch into `dev`. Prefer merging `origin/<branch>` after fetch; if only local `<branch>` exists, merge that.
14. If the merge fails or has conflicts, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment with the failing command and conflict/error summary, and leave it in `Merging`.
15. Run relevant tests, build, lint, and manual checks from `merging-<task_id>` to verify the merged feature works as intended and does not regress nearby behavior.
16. If tests or verification fail, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment with commands run, expected behavior, observed behavior, and relevant paths, and leave it in `Merging`.
17. Push the merged `dev` branch to the git server with `git push origin dev`.
18. If pushing `dev` fails, run `/root/.config/opencode/scripts/color-change.py` to mark the task `red`, add a comment with the push error summary, and leave it in `Merging`.
19. If pushing succeeds, resolve the project by exact name with `kanboard_get_projects`, fetch columns with `kanboard_get_columns`, confirm `QA` exists exactly once, add a comment summarizing the merge, tests run, and pushed `dev` commit hash; move the task to `QA`; run `/root/.config/opencode/scripts/color-change.py` to mark it `yellow`; then remove the `merging-<task_id>` working directory.

## Git Rules

Work only inside `merging-<task_id>` for merge operations. Do not merge directly in `src`. Do not push any branch except `dev` from this handler.

Before pushing `dev`, inspect status and log. Do not push if the working tree is dirty, if merge conflicts remain, or if verification failed.

After `dev` has been pushed, the task has been moved to `QA`, and the final yellow color has been verified, remove the `merging-<task_id>` working directory. If cleanup fails after the task has already been moved and marked yellow, add a Kanboard comment with the cleanup issue but do not move the task back.

## Failure Handling

On any error, mark the task red when possible, add a concrete Kanboard comment explaining the issue, and leave the task in `Merging`. Do not move the task after a failed required color change.

## Completion Rules

Do not perform final QA beyond merge verification. Do not change task colors with MCP; every color change must use `/root/.config/opencode/scripts/color-change.py`.
