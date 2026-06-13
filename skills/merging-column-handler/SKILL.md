---
name: merging-column-handler
description: Use ONLY when handling a yellow Kanboard task in the Merging column after the orchestrator has already attempted a merge and conflicts must be resolved.
---

# Merging Column Handler

Resolve existing merge conflicts in the current `merging-<task_id>` directory and fill the pre-created output JSON. The orchestrator already prepared the merge directory and attempted the merge. Do not restart the workflow or perform finalization work; only resolve the existing conflicts.

## Inputs

Expected prompt format:

```text
project_name: <exact Kanboard project name>
task_id: <Kanboard task id>
kanboard_url: <optional Kanboard base URL>
kanboard_username: <optional API username>
kanboard_token_path: <optional token file path>
workspace: <workspace root containing plans/ and src/>
merge_dir: <current merge directory, usually merging-<task_id>>
output_json: <absolute path to output-<task_id>.json>
```

The orchestrator pre-creates the output file at the exact absolute path provided as `output_json` and runs this skill with the current working directory set to `merging-<task_id>`. You MUST fill that exact file. Do not write `/output-<task_id>.json`, do not write a relative `output-<task_id>.json`, and do not create any other output JSON file.

## Available Opencode Tools

Use only these tool categories for this skill:

```text
kanboard_get_task_details, kanboard_get_task_comments
read, glob, grep
write/edit tools
```

Tool usage rules:

1. Use `kanboard_get_task_details` and `kanboard_get_task_comments` only for context if needed.
2. Use `read`, `glob`, and `grep` to inspect conflicted files and nearby code.
3. Use write/edit tools to resolve merge conflicts in the current merge directory and to fill the exact absolute `output_json` path.
4. Do not move the Kanboard task, change its color, or add Kanboard comments directly.
5. Do not run workflow finalization commands. The orchestrator owns finalizing and publishing the resolved merge after this skill succeeds.

## Required Workflow

1. Inspect the current merge-conflicted working directory.
2. Resolve conflict markers and reconcile both sides of the change correctly.
3. Keep the resolution minimal and aligned with the ticket intent.
4. Remove temporary conflict-resolution notes, logs, scratch files, generated debug artifacts, test output, and any dirty files unrelated to the actual conflict resolution before reporting success.
5. If conflicts cannot be resolved safely, write `status: "failure"` with at least one useful comment explaining the blocker.
6. If conflicts are resolved, write `status: "success"` with comments summarizing the resolution.

## Conflict Resolution Rules

Do not perform new feature work. Only resolve the conflicts created by the orchestrator's already-attempted merge. Preserve the functionality described in the ticket while reconciling both sides of the merge. Before reporting success, verify that no conflict markers remain, including `<<<<<<<`, `=======`, and `>>>>>>>`. If preserving the ticket behavior is unclear or resolving the conflict requires a product decision, missing context, or a non-trivial redesign, report `failure` instead of guessing.

## Output JSON

Fill the pre-created file at the exact absolute `output_json` path with this exact JSON shape before reporting completion:

```json
{
  "task_id": 123,
  "status": "success",
  "comments": ["Resolved merge conflicts in the affected files."]
}
```

Failure output MUST use `status: "failure"` and MUST include at least one useful string in `comments`.

Required fields:

1. `task_id`: integer matching the input task id.
2. `status`: exactly `success` or `failure`.
3. `comments`: array of strings for the orchestrator to add to the Kanboard ticket. If `status` is `failure`, this array MUST contain at least one useful error comment.

## Completion Rules

Never report completion until the exact absolute `output_json` path contains valid JSON matching the contract. Before success, clean any test output, logs, scratch files, temporary files, generated debug files, or unrelated dirty files. The orchestrator, not this skill, will finalize the resolved merge, post comments, change color, and advance the ticket.
