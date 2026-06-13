#!/usr/bin/env python3
"""Deterministic Kanboard autoloop orchestrator for opencode handler skills."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter
from typing import Any


DEFAULT_KANBOARD_URL = "http://172.17.0.1:8080/"
DEFAULT_KANBOARD_USERNAME = "admin"
DEFAULT_TOKEN_PATH = "/token"
DEFAULT_TICKET_LOCK_URL = "http://172.17.0.1:8000/"
DEFAULT_QA_DURATION = "10m"
DEFAULT_TEMPLATE = "/root/.config/opencode/templates/kanboard-handler-prompt.txt"
DEFAULT_COLOR_CHANGE_SCRIPT = "/root/.config/opencode/scripts/color-change.py"
REQUIRED_COLUMNS = ("Backlog", "To Do", "Plan", "WIP", "Merging", "QA", "Done")
ROUTES = {
    "To Do": "to-do-column-handler",
    "Plan": "plan-column-handler",
    "WIP": "wip-column-handler",
    "Merging": "merging-column-handler",
    "QA": "qa-column-handler",
}
NEXT_COLUMNS = {
    "To Do": "Plan",
    "Plan": "WIP",
    "WIP": "Merging",
    "Merging": "QA",
    "QA": "Done",
}
VALID_QA_DURATION = re.compile(r"^[1-9][0-9]*[smh]$")


class OrchestratorError(RuntimeError):
    pass


class KanboardError(OrchestratorError):
    pass


class LockError(OrchestratorError):
    pass


class SourceRefreshError(OrchestratorError):
    def __init__(self, message: str, command: str | None = None, output: str | None = None) -> None:
        super().__init__(message)
        self.command = command
        self.output = output


@dataclass(frozen=True)
class Column:
    id: int
    title: str


@dataclass(frozen=True)
class SelectedTask:
    id: int
    title: str
    column: Column
    handler_skill: str
    swimlane_id: int
    merge_lock_acquired: bool = False


class KanboardClient:
    def __init__(self, base_url: str, username: str, token_path: str) -> None:
        self.url = jsonrpc_url(base_url)
        self.username = username
        self.token = read_token(token_path)
        self.request_id = 0

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        self.request_id += 1
        body = json.dumps(
            {"jsonrpc": "2.0", "method": method, "id": self.request_id, "params": params}
        ).encode("utf-8")
        auth = base64.b64encode(f"{self.username}:{self.token}".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise KanboardError(f"HTTP {exc.code} from Kanboard for {method}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise KanboardError(f"Kanboard request failed for {method}: {exc}") from exc

        if "error" in payload:
            raise KanboardError(f"Kanboard JSON-RPC error for {method}: {payload['error']}")
        if "result" not in payload:
            raise KanboardError(f"Kanboard JSON-RPC response missing result for {method}: {payload}")
        return payload["result"]

    def find_project(self, project_name: str) -> dict[str, Any]:
        result = self.rpc("getAllProjects", {})
        if not isinstance(result, list):
            raise KanboardError(f"getAllProjects returned unexpected result: {result!r}")

        matches = [project for project in result if isinstance(project, dict) and project.get("name") == project_name]
        if not matches:
            raise KanboardError(f"project {project_name!r} was not found")
        if len(matches) > 1:
            raise KanboardError(f"project {project_name!r} matched more than once")
        return matches[0]

    def get_columns(self, project_id: int) -> list[dict[str, Any]]:
        result = self.rpc("getColumns", {"project_id": project_id})
        if not isinstance(result, list):
            raise KanboardError(f"getColumns returned unexpected result: {result!r}")
        return [column for column in result if isinstance(column, dict)]

    def get_active_tasks(self, project_id: int) -> list[dict[str, Any]]:
        result = self.rpc("getAllTasks", {"project_id": project_id, "status_id": 1})
        if not isinstance(result, list):
            raise KanboardError(f"getAllTasks returned unexpected result: {result!r}")
        return [task for task in result if isinstance(task, dict)]

    def get_task(self, task_id: int) -> dict[str, Any]:
        result = self.rpc("getTask", {"task_id": task_id})
        if not isinstance(result, dict) or not result:
            raise KanboardError(f"getTask returned unexpected result for task {task_id}: {result!r}")
        return result

    def add_comment(self, task_id: int, content: str) -> None:
        user_id = self.current_user_id()
        result = self.rpc("createComment", {"task_id": task_id, "user_id": user_id, "content": content})
        if result in (False, None, 0, "0"):
            raise KanboardError(f"createComment returned unexpected result: {result!r}")

    def get_comments(self, task_id: int) -> list[dict[str, Any]]:
        result = self.rpc("getAllComments", {"task_id": task_id})
        if not isinstance(result, list):
            raise KanboardError(f"getAllComments returned unexpected result for task {task_id}: {result!r}")
        return [comment for comment in result if isinstance(comment, dict)]

    def move_task(self, project_id: int, task_id: int, column_id: int, swimlane_id: int) -> None:
        result = self.rpc(
            "moveTaskPosition",
            {
                "project_id": project_id,
                "task_id": task_id,
                "column_id": column_id,
                "position": 1,
                "swimlane_id": swimlane_id,
            },
        )
        if result is not True:
            raise KanboardError(f"moveTaskPosition returned unexpected result for task {task_id}: {result!r}")

        moved_task = self.get_task(task_id)
        observed_column = int_field(moved_task.get("column_id"), f"column_id for moved task {task_id}")
        if observed_column != column_id:
            raise KanboardError(
                f"move verification failed for task {task_id}: observed column {observed_column}, expected {column_id}"
            )

    def current_user_id(self) -> int:
        try:
            result = self.rpc("getMe", {})
            if isinstance(result, dict) and result.get("id") is not None:
                return int(result["id"])
        except KanboardError:
            pass

        try:
            result = self.rpc("getUserByName", {"username": self.username})
            if isinstance(result, dict) and result.get("id") is not None:
                return int(result["id"])
        except KanboardError:
            pass

        return 1


def jsonrpc_url(base_url: str) -> str:
    if base_url.endswith("/jsonrpc.php"):
        return base_url
    return base_url.rstrip("/") + "/kanboard/jsonrpc.php"


def read_token(path: str) -> str:
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise KanboardError(f"failed to read token file {path!r}: {exc}") from exc

    if not token:
        raise KanboardError(f"token file {path!r} is empty")
    return token


def int_field(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise KanboardError(f"invalid {field_name}: {value!r}") from exc


def run_command(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise SourceRefreshError(
            f"{' '.join(command)} failed in {cwd}: {detail}",
            command=" ".join(command),
            output=detail,
        )
    return result


def git_branch_exists(repo: Path, ref: str) -> bool:
    result = run_command(["git", "show-ref", "--verify", "--quiet", ref], repo, check=False)
    return result.returncode == 0


def checkout_dev(repo: Path) -> None:
    if git_branch_exists(repo, "refs/heads/dev"):
        run_command(["git", "checkout", "dev"], repo)
        return
    if git_branch_exists(repo, "refs/remotes/origin/dev"):
        run_command(["git", "checkout", "-b", "dev", "--track", "origin/dev"], repo)
        return
    run_command(["git", "checkout", "dev"], repo)


def git_status_short(repo: Path) -> str:
    return run_command(["git", "status", "--short"], repo).stdout.strip()


def git_has_changes(repo: Path) -> bool:
    return bool(git_status_short(repo))


def git_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def is_nothing_to_commit(output: str) -> bool:
    lowered = output.lower()
    return "nothing to commit" in lowered or "no changes added to commit" in lowered


def is_empty_push(output: str) -> bool:
    return "everything up-to-date" in output.lower() or "everything up to date" in output.lower()


def git_commit_all(repo: Path, message: str) -> bool:
    run_command(["git", "add", "-A"], repo)
    result = run_command(["git", "commit", "-m", message], repo, check=False)
    output = git_output(result)
    if result.returncode == 0:
        return True
    if is_nothing_to_commit(output):
        return False
    raise SourceRefreshError(
        f"git commit failed in {repo}: {output or f'exit code {result.returncode}'}",
        command="git commit -m",
        output=output or f"exit code {result.returncode}",
    )


def git_commit_no_edit_all(repo: Path) -> bool:
    run_command(["git", "add", "-A"], repo)
    result = run_command(["git", "commit", "--no-edit"], repo, check=False)
    output = git_output(result)
    if result.returncode == 0:
        return True
    if is_nothing_to_commit(output):
        return False
    raise SourceRefreshError(
        f"git commit --no-edit failed in {repo}: {output or f'exit code {result.returncode}'}",
        command="git commit --no-edit",
        output=output or f"exit code {result.returncode}",
    )


def git_push(repo: Path, *args: str) -> bool:
    result = run_command(["git", "push", *args], repo, check=False)
    output = git_output(result)
    if is_empty_push(output):
        return True
    if result.returncode == 0:
        return False
    raise SourceRefreshError(
        f"git push failed in {repo}: {output or f'exit code {result.returncode}'}",
        command="git push",
        output=output or f"exit code {result.returncode}",
    )


def git_rev_parse(repo: Path, ref: str = "HEAD") -> str:
    return run_command(["git", "rev-parse", "--short", ref], repo).stdout.strip()


def remote_branch_exists(repo: Path, branch: str) -> bool:
    result = run_command(["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], repo, check=False)
    return result.returncode == 0


def prepare_copy(source: Path, destination: Path) -> None:
    if destination.exists():
        raise OrchestratorError(f"working directory already exists: {destination}")
    shutil.copytree(source, destination)


def cleanup_directory(path: Path) -> str | None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)
    return None


def ensure_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if (path / ".git").exists():
        return

    result = run_command(["git", "init", "-b", "dev"], path, check=False)
    if result.returncode == 0:
        return

    run_command(["git", "init"], path)
    run_command(["git", "branch", "-M", "dev"], path)


def ensure_workspace(workspace: Path) -> None:
    ensure_git_repo(workspace / "plans")
    ensure_git_repo(workspace / "src")


def validate_columns(raw_columns: list[dict[str, Any]]) -> dict[str, Column]:
    columns_by_title: dict[str, list[Column]] = {title: [] for title in REQUIRED_COLUMNS}
    for raw_column in raw_columns:
        title = raw_column.get("title")
        if title not in columns_by_title:
            continue
        columns_by_title[title].append(Column(id=int_field(raw_column.get("id"), f"column id for {title}"), title=title))

    problems: list[str] = []
    for title in REQUIRED_COLUMNS:
        count = len(columns_by_title[title])
        if count != 1:
            problems.append(f"{title} exists {count} times")
    if problems:
        raise KanboardError("required Kanboard columns are missing or duplicated: " + "; ".join(problems))

    return {title: matches[0] for title, matches in columns_by_title.items()}


def post_ticket_lock_endpoint(
    ticket_lock_url: str,
    project_name: str,
    task_id: int,
    column_title: str,
    path: str,
    expected: set[str],
) -> str:
    body = json.dumps(
        {
            "requested-ticket-id": str(task_id),
            "current-column": column_title,
            "project-name": project_name,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        qserver_url(ticket_lock_url, path),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LockError(f"ticket lock endpoint {path!r} failed for task {task_id}: {exc}") from exc

    if text not in expected:
        raise LockError(f"ticket lock endpoint {path!r} returned {text!r} for task {task_id}; expected one of {sorted(expected)}")
    return text


def qserver_url(ticket_lock_url: str, path: str) -> str:
    return ticket_lock_url.rstrip("/") + "/" + path.lstrip("/")


def request_ticket_lock(ticket_lock_url: str, project_name: str, task_id: int, column_title: str) -> str:
    return post_ticket_lock_endpoint(ticket_lock_url, project_name, task_id, column_title, "take-lock", {"ok", "taken"})


def remove_ticket_lock(ticket_lock_url: str, project_name: str, task_id: int, column_title: str) -> None:
    post_ticket_lock_endpoint(ticket_lock_url, project_name, task_id, column_title, "remove-ticket-lock", {"ok"})


def post_project_merge_endpoint(ticket_lock_url: str, project_name: str, path: str, expected: set[str]) -> str:
    body = json.dumps(project_name).encode("utf-8")
    request = urllib.request.Request(
        qserver_url(ticket_lock_url, path),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LockError(f"merge lock request failed for project {project_name!r}: {exc}") from exc

    if text not in expected:
        raise LockError(f"merge lock endpoint {path!r} returned {text!r}; expected one of {sorted(expected)}")
    return text


def request_project_merge_lock(ticket_lock_url: str, project_name: str) -> str:
    return post_project_merge_endpoint(ticket_lock_url, project_name, "can-merge-now", {"yes", "no"})


def release_project_merge_lock(ticket_lock_url: str, project_name: str) -> None:
    post_project_merge_endpoint(ticket_lock_url, project_name, "done-merging", {"ok"})


def release_project_merge_lock_best_effort(args: argparse.Namespace) -> None:
    try:
        release_project_merge_lock(args.ticket_lock_url, args.project_name)
    except OrchestratorError as exc:
        print(f"warning: failed to release project merge lock: {exc}", file=sys.stderr, flush=True)


def select_task(
    client: KanboardClient,
    project_id: int,
    project_name: str,
    columns: dict[str, Column],
    ticket_lock_url: str,
) -> tuple[SelectedTask | None, list[int], list[int], list[int]]:
    column_by_id = {column.id: column for column in columns.values()}
    ignored: list[int] = []
    lock_taken: list[int] = []
    merge_locked: list[int] = []

    for raw_task in client.get_active_tasks(project_id):
        task_id = int_field(raw_task.get("id"), "task id")
        column_id = int_field(raw_task.get("column_id"), f"column_id for task {task_id}")
        column = column_by_id.get(column_id)
        if column is None:
            ignored.append(task_id)
            continue
        if column.title in {"Backlog", "Done"}:
            ignored.append(task_id)
            continue
        if raw_task.get("color_id") != "yellow":
            ignored.append(task_id)
            continue
        handler_skill = ROUTES.get(column.title)
        if handler_skill is None:
            ignored.append(task_id)
            continue

        merge_lock_acquired = False
        if column.title == "Merging":
            merge_status = request_project_merge_lock(ticket_lock_url, project_name)
            if merge_status == "no":
                merge_locked.append(task_id)
                continue
            merge_lock_acquired = True

        try:
            lock_status = request_ticket_lock(ticket_lock_url, project_name, task_id, column.title)
        except Exception:
            if merge_lock_acquired:
                try:
                    release_project_merge_lock(ticket_lock_url, project_name)
                except OrchestratorError as exc:
                    print(f"warning: failed to release project merge lock: {exc}", file=sys.stderr, flush=True)
            raise
        if lock_status == "taken":
            if merge_lock_acquired:
                release_project_merge_lock(ticket_lock_url, project_name)
            lock_taken.append(task_id)
            continue

        return (
            SelectedTask(
                id=task_id,
                title=str(raw_task.get("title") or ""),
                column=column,
                handler_skill=handler_skill,
                swimlane_id=int_field(raw_task.get("swimlane_id", 0), f"swimlane_id for task {task_id}"),
                merge_lock_acquired=merge_lock_acquired,
            ),
            ignored,
            lock_taken,
            merge_locked,
        )

    return None, ignored, lock_taken, merge_locked


def unlock_one_purple_task(
    args: argparse.Namespace,
    client: KanboardClient,
    project_id: int,
    columns: dict[str, Column],
) -> int | None:
    column_by_id = {column.id: column for column in columns.values()}
    for raw_task in client.get_active_tasks(project_id):
        task_id = int_field(raw_task.get("id"), "task id")
        if raw_task.get("color_id") != "purple":
            continue

        column_id = int_field(raw_task.get("column_id"), f"column_id for task {task_id}")
        column = column_by_id.get(column_id)
        if column is None or column.title in {"Backlog", "Done"} or column.title not in ROUTES:
            continue

        remove_ticket_lock(args.ticket_lock_url, args.project_name, task_id, column.title)
        change_color(args, task_id, "yellow")
        return task_id

    return None


def change_color(args: argparse.Namespace, task_id: int, color: str) -> None:
    command = [
        args.color_change_script,
        args.project_name,
        str(task_id),
        color,
        "--kanboard-url",
        args.kanboard_url,
        "--username",
        args.kanboard_username,
        "--token-path",
        args.kanboard_token_path,
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise OrchestratorError(f"failed to mark task {task_id} {color}: {detail}")


def mark_red_and_comment(
    args: argparse.Namespace,
    client: KanboardClient,
    task_id: int,
    comment: str,
) -> None:
    change_color(args, task_id, "red")
    client.add_comment(task_id, comment)


def mark_red_git_error(
    args: argparse.Namespace,
    client: KanboardClient,
    task: SelectedTask,
    action: str,
    exc: Exception,
) -> None:
    if isinstance(exc, SourceRefreshError):
        command = exc.command or "unknown"
        output = exc.output or str(exc)
    else:
        command = "unknown"
        output = str(exc)
    mark_red_and_comment(args, client, task.id, f"Error with git {action}\n\nCommand: {command}\nOutput:\n{output}")


def empty_push_comment(task: SelectedTask) -> str:
    return f"Empty git push happened while task was in column {task.column.title}: nothing new to push."


def latest_comment_value(client: KanboardClient, task_id: int, prefix: str) -> str | None:
    comments = client.get_comments(task_id)
    for comment in reversed(comments):
        content = str(comment.get("comment") or comment.get("content") or "")
        for line in reversed(content.splitlines()):
            stripped = line.strip()
            if stripped.startswith(prefix):
                return stripped[len(prefix):].strip()
    return None


def output_comment_value(output: dict[str, Any], prefix: str) -> str | None:
    for comment in output.get("comments", []):
        for line in str(comment).splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                return stripped[len(prefix):].strip()
    return None


def strip_output_comments_with_prefix(output: dict[str, Any], prefix: str) -> None:
    filtered: list[str] = []
    for comment in output.get("comments", []):
        lines = str(comment).splitlines()
        if any(line.strip().startswith(prefix) for line in lines):
            continue
        filtered.append(str(comment))
    output["comments"] = filtered


def validate_workspace_plan_path(args: argparse.Namespace, task: SelectedTask, plan_file: str) -> str:
    workspace = Path(args.workspace).resolve()
    plans_dir = (workspace / "plans").resolve()
    plan_path = (workspace / plan_file).resolve()
    if plans_dir not in plan_path.parents or not plan_path.exists():
        raise OrchestratorError(f"invalid PLAN_FILE for task {task.id}: {plan_file}")
    return plan_path.relative_to(workspace).as_posix()


def resolve_plan_file_from_comments(args: argparse.Namespace, client: KanboardClient, task: SelectedTask) -> str:
    plan_file = latest_comment_value(client, task.id, "PLAN_FILE:")
    if not plan_file:
        comment = f"No PLAN_FILE available for {task.column.title}; orchestrator cannot continue."
        mark_red_and_comment(args, client, task.id, comment)
        raise OrchestratorError(comment)
    try:
        return validate_workspace_plan_path(args, task, plan_file)
    except OrchestratorError as exc:
        mark_red_and_comment(args, client, task.id, f"Invalid PLAN_FILE for {task.column.title}; orchestrator cannot continue.\n\n{exc}")
        raise


def refresh_repo(args: argparse.Namespace, client: KanboardClient, task: SelectedTask, repo_name: str) -> None:
    repo = Path(args.workspace) / repo_name
    if not repo.exists() or not (repo / ".git").exists():
        message = f"Error with refresh\n\n{repo} is missing or is not a git repository."
        mark_red_and_comment(args, client, task.id, message)
        raise SourceRefreshError(message)

    try:
        status = run_command(["git", "status", "--short"], repo)
    except SourceRefreshError as exc:
        command = exc.command or "git status --short"
        output = exc.output or str(exc)
        mark_red_and_comment(
            args,
            client,
            task.id,
            f"Error with refresh\n\nCommand: {command}\nOutput:\n{output}",
        )
        raise

    if status.stdout.strip():
        message = (
            "Error with refresh\n\n"
            f"Command: git status --short\n"
            f"Output:\n{status.stdout.strip()}"
        )
        mark_red_and_comment(args, client, task.id, message)
        raise SourceRefreshError(f"{repo_name} is dirty", command="git status --short", output=status.stdout.strip())

    try:
        run_command(["git", "fetch", "--all", "--prune"], repo)
        checkout_dev(repo)
        run_command(["git", "pull", "--ff-only", "origin", "dev"], repo)
    except SourceRefreshError as exc:
        command = exc.command or "unknown"
        output = exc.output or str(exc)
        mark_red_and_comment(
            args,
            client,
            task.id,
            f"Error with refresh\n\nCommand: {command}\nOutput:\n{output}",
        )
        raise


def refresh_workspace(args: argparse.Namespace, client: KanboardClient, task: SelectedTask) -> None:
    refresh_repo(args, client, task, "plans")
    refresh_repo(args, client, task, "src")


def validate_template(template: str, context: dict[str, str]) -> None:
    fields = [field_name for _, field_name, _, _ in Formatter().parse(template) if field_name]
    missing = sorted({field.split(".", 1)[0].split("[", 1)[0] for field in fields} - set(context))
    if missing:
        raise OrchestratorError(f"prompt template has unknown placeholders: {', '.join(missing)}")


def render_prompt(args: argparse.Namespace, task: SelectedTask, plan_file: str = "") -> str:
    template_path = Path(args.prompt_template)
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OrchestratorError(f"failed to read prompt template {template_path}: {exc}") from exc

    qa_duration_block = f"qa_duration: {args.qa_duration}\n" if task.handler_skill == "qa-column-handler" else ""
    plan_file_prompt = str((Path(args.workspace) / plan_file).resolve()) if plan_file else ""
    context = {
        "handler_skill": task.handler_skill,
        "project_name": args.project_name,
        "task_id": str(task.id),
        "task_title": task.title,
        "column_title": task.column.title,
        "column_id": str(task.column.id),
        "qa_duration": args.qa_duration,
        "qa_duration_block": qa_duration_block,
        "kanboard_url": args.kanboard_url,
        "kanboard_username": args.kanboard_username,
        "kanboard_token_path": args.kanboard_token_path,
        "ticket_lock_url": args.ticket_lock_url,
        "workspace": str(Path(args.workspace).resolve()),
        "output_path": str(handler_output_path(args, task)),
        "implementation_dir": str(implementation_dir(args, task)),
        "merge_dir": str(merge_dir(args, task)),
        "qa_dir": str(qa_dir(args, task)),
        "branch_name": implementation_branch(task),
        "plan_file": plan_file_prompt,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    validate_template(template, context)
    try:
        return template.format(**context)
    except (KeyError, IndexError, ValueError) as exc:
        raise OrchestratorError(f"failed to render prompt template {template_path}: {exc}") from exc


def write_run_files(args: argparse.Namespace, task: SelectedTask, prompt: str) -> None:
    run_dir = Path(args.run_dir) / args.run_id / f"task-{task.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "handler").write_text(task.handler_skill + "\n", encoding="utf-8")
    (run_dir / "column").write_text(task.column.title + "\n", encoding="utf-8")
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")


def run_handler(args: argparse.Namespace, task: SelectedTask, prompt: str, cwd: Path | None = None) -> int:
    command = [args.opencode_bin, "run"]
    if args.model:
        command.extend(["-m", args.model])
    for extra_arg in args.opencode_arg:
        command.append(extra_arg)
    command.append(prompt)

    print(f"Routing task {task.id} in {task.column.title!r} to {task.handler_skill}.", flush=True)
    if args.dry_run:
        print("Dry run: would execute:", " ".join(command[:-1]), "<rendered prompt>", flush=True)
        print("\n--- Rendered Prompt ---\n" + prompt, flush=True)
        return 0

    return subprocess.run(command, cwd=str(cwd or Path(args.workspace)), check=False).returncode


def handler_output_path(args: argparse.Namespace, task: SelectedTask) -> Path:
    return Path(args.workspace) / f"output-{task.id}.json"


def implementation_branch(task: SelectedTask) -> str:
    return f"task-{task.id}"


def implementation_dir(args: argparse.Namespace, task: SelectedTask) -> Path:
    return Path(args.workspace) / f"src-{task.id}"


def merge_dir(args: argparse.Namespace, task: SelectedTask) -> Path:
    return Path(args.workspace) / f"merging-{task.id}"


def qa_dir(args: argparse.Namespace, task: SelectedTask) -> Path:
    return Path(args.workspace) / f"qa-{task.id}"


def remove_output_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise OrchestratorError(f"failed to delete handler output {path}: {exc}") from exc


def create_pending_output_file(args: argparse.Namespace, task: SelectedTask) -> None:
    path = handler_output_path(args, task)
    payload = {
        "task_id": task.id,
        "status": "pending",
        "comments": [],
    }
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise OrchestratorError(f"failed to create handler output {path}: {exc}") from exc


def failure_output(task: SelectedTask, comment: str) -> dict[str, Any]:
    return {"task_id": task.id, "status": "failure", "comments": [comment]}


def malformed_output(task: SelectedTask, message: str, content: str | None = None) -> dict[str, Any]:
    comment = f"Skill returned malformed output\n\n{message}"
    if content is not None:
        comment += f"\n\nOutput:\n{content}"
    return failure_output(task, comment)


def read_handler_output(args: argparse.Namespace, client: KanboardClient, task: SelectedTask) -> dict[str, Any]:
    path = handler_output_path(args, task)
    if not path.exists():
        return failure_output(task, "Skill didn't return any output")

    try:
        raw_file_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return malformed_output(task, str(exc))

    try:
        raw_output = raw_file_text.replace("\\n", "")
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return malformed_output(task, str(exc), raw_file_text)

    if not isinstance(payload, dict):
        return malformed_output(task, "output JSON root must be an object", raw_file_text)

    if payload.get("task_id") != task.id:
        return malformed_output(task, f"task_id must be {task.id}, got {payload.get('task_id')!r}", raw_file_text)

    status = payload.get("status")
    if status == "pending":
        return failure_output(task, "Skill didn't return any output")
    if status not in {"success", "failure"}:
        return malformed_output(task, "status must be exactly 'success' or 'failure'", raw_file_text)

    comments = payload.get("comments", [])
    if not isinstance(comments, list) or any(not isinstance(comment, str) for comment in comments):
        return malformed_output(task, "comments must be an array of strings", raw_file_text)
    payload["comments"] = comments
    if status == "failure" and not any(comment.strip() for comment in comments):
        payload["comments"] = ["Skill didn't provide error"]

    return payload


def add_output_comments(client: KanboardClient, task_id: int, output: dict[str, Any]) -> None:
    for comment in output["comments"]:
        if comment.strip():
            client.add_comment(task_id, comment)


def handle_failure_output(args: argparse.Namespace, client: KanboardClient, task: SelectedTask, output: dict[str, Any]) -> None:
    change_color(args, task.id, "red")
    add_output_comments(client, task.id, output)
    remove_output_file(handler_output_path(args, task))


def advance_success(
    args: argparse.Namespace,
    client: KanboardClient,
    project_id: int,
    columns: dict[str, Column],
    task: SelectedTask,
    output: dict[str, Any],
    extra_comments: list[str] | None = None,
) -> None:
    next_column_title = NEXT_COLUMNS.get(task.column.title)
    if next_column_title is None:
        raise OrchestratorError(f"no next column is configured for {task.column.title!r}")

    next_column = columns[next_column_title]
    add_output_comments(client, task.id, output)
    for comment in extra_comments or []:
        if comment.strip():
            client.add_comment(task.id, comment)
    client.move_task(project_id, task.id, next_column.id, task.swimlane_id)
    change_color(args, task.id, "yellow")
    remove_output_file(handler_output_path(args, task))


def complete_from_handler_output(
    args: argparse.Namespace,
    client: KanboardClient,
    project_id: int,
    columns: dict[str, Column],
    task: SelectedTask,
    output: dict[str, Any],
) -> None:
    if output["status"] == "failure":
        handle_failure_output(args, client, task, output)
        return
    advance_success(args, client, project_id, columns, task, output)


def commit_push_plan(args: argparse.Namespace, client: KanboardClient, task: SelectedTask, output: dict[str, Any]) -> list[str]:
    plan_file = output_comment_value(output, "PLAN_FILE:")
    if not plan_file:
        mark_red_and_comment(args, client, task.id, "Skill didn't provide PLAN_FILE")
        remove_output_file(handler_output_path(args, task))
        raise OrchestratorError("plan handler did not provide PLAN_FILE")

    plans_dir = (Path(args.workspace) / "plans").resolve()
    try:
        canonical_plan_file = validate_workspace_plan_path(args, task, plan_file)
    except OrchestratorError:
        mark_red_and_comment(args, client, task.id, f"Invalid PLAN_FILE: {plan_file}")
        remove_output_file(handler_output_path(args, task))
        raise

    try:
        git_commit_all(plans_dir, f"Add plan for Kanboard task {task.id}")
        empty_push = git_push(plans_dir, "origin", "dev")
    except SourceRefreshError as exc:
        mark_red_git_error(args, client, task, "plan commit/push", exc)
        remove_output_file(handler_output_path(args, task))
        raise

    strip_output_comments_with_prefix(output, "PLAN_FILE:")
    comments = [f"PLAN_FILE: {canonical_plan_file}"]
    if empty_push:
        comments.append(empty_push_comment(task))
    return comments


def prepare_wip_directory(args: argparse.Namespace, task: SelectedTask) -> Path:
    source = Path(args.workspace) / "src"
    destination = implementation_dir(args, task)
    prepare_copy(source, destination)
    run_command(["git", "checkout", "-B", implementation_branch(task)], destination)
    return destination


def prepare_qa_directory(args: argparse.Namespace, task: SelectedTask) -> Path:
    source = Path(args.workspace) / "src"
    destination = qa_dir(args, task)
    prepare_copy(source, destination)
    return destination


def commit_push_wip(args: argparse.Namespace, client: KanboardClient, task: SelectedTask) -> list[str]:
    repo = implementation_dir(args, task)
    branch = implementation_branch(task)
    try:
        git_commit_all(repo, f"Implement Kanboard task {task.id}")
        commit = git_rev_parse(repo)
        empty_push = git_push(repo, "-u", "origin", branch)
    except SourceRefreshError as exc:
        mark_red_git_error(args, client, task, "implementation commit/push", exc)
        remove_output_file(handler_output_path(args, task))
        raise

    comments = [f"BRANCH_NAME: {branch}", f"Implementation branch pushed: {branch} ({commit})"]
    if empty_push:
        comments.append(empty_push_comment(task))
    return comments


def unmerged_files(repo: Path) -> list[str]:
    result = run_command(["git", "diff", "--name-only", "--diff-filter=U"], repo, check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def commit_push_merge_resolution(args: argparse.Namespace, client: KanboardClient, task: SelectedTask, repo: Path) -> tuple[str, list[str]]:
    if unmerged_files(repo):
        mark_red_and_comment(args, client, task.id, "Merge conflicts were not fully resolved")
        remove_output_file(handler_output_path(args, task))
        raise OrchestratorError("merge conflicts remain after handler success")

    try:
        git_commit_no_edit_all(repo)
        commit = git_rev_parse(repo)
        empty_push = git_push(repo, "origin", "dev")
    except SourceRefreshError as exc:
        mark_red_git_error(args, client, task, "merge conflict resolution commit/push", exc)
        remove_output_file(handler_output_path(args, task))
        raise
    comments = [empty_push_comment(task)] if empty_push else []
    return commit, comments


def merge_source_ref(repo: Path, branch: str) -> str:
    if remote_branch_exists(repo, branch):
        return f"origin/{branch}"
    if git_branch_exists(repo, f"refs/heads/{branch}"):
        return branch
    raise SourceRefreshError(f"branch {branch!r} was not found", command="git show-ref", output=branch)


def handle_merging_task(
    args: argparse.Namespace,
    client: KanboardClient,
    project_id: int,
    columns: dict[str, Column],
    task: SelectedTask,
) -> None:
    branch = latest_comment_value(client, task.id, "BRANCH_NAME:")
    if not branch:
        mark_red_and_comment(args, client, task.id, "No BRANCH_NAME comment was found for merging")
        raise OrchestratorError("missing BRANCH_NAME for merging task")

    repo = merge_dir(args, task)
    try:
        prepare_copy(Path(args.workspace) / "src", repo)
        run_command(["git", "fetch", "--all", "--prune"], repo)
        source_ref = merge_source_ref(repo, branch)
        checkout_dev(repo)
        run_command(["git", "pull", "--ff-only", "origin", "dev"], repo)
        merge_result = run_command(["git", "merge", "--no-edit", source_ref], repo, check=False)
    except (OSError, SourceRefreshError, OrchestratorError) as exc:
        mark_red_git_error(args, client, task, "merge setup", exc)
        raise

    if merge_result.returncode == 0:
        try:
            commit = git_rev_parse(repo)
            empty_push = git_push(repo, "origin", "dev")
        except SourceRefreshError as exc:
            mark_red_git_error(args, client, task, "clean merge push", exc)
            raise

        output = {"task_id": task.id, "status": "success", "comments": []}
        comments = [f"Merged {branch} into dev and pushed {commit}."]
        if empty_push:
            comments.append(empty_push_comment(task))
        advance_success(
            args,
            client,
            project_id,
            columns,
            task,
            output,
            comments,
        )
        cleanup_error = cleanup_directory(repo)
        if cleanup_error:
            client.add_comment(task.id, f"Cleanup warning: failed to remove {repo}: {cleanup_error}")
        return

    conflicts = unmerged_files(repo)
    if not conflicts:
        output = merge_result.stderr.strip() or merge_result.stdout.strip() or f"exit code {merge_result.returncode}"
        mark_red_and_comment(args, client, task.id, f"Merge failed without conflicts\n\n{output}")
        raise OrchestratorError("merge failed without conflict files")

    create_pending_output_file(args, task)
    prompt = render_prompt(args, task)
    write_run_files(args, task, prompt)
    run_handler(args, task, prompt, cwd=repo)
    output = read_handler_output(args, client, task)
    if output["status"] == "failure":
        handle_failure_output(args, client, task, output)
        return

    commit, empty_comments = commit_push_merge_resolution(args, client, task, repo)
    comments = [f"Resolved merge conflicts for {branch} and pushed dev commit {commit}."]
    comments.extend(empty_comments)
    advance_success(
        args,
        client,
        project_id,
        columns,
        task,
        output,
        comments,
    )
    cleanup_error = cleanup_directory(repo)
    if cleanup_error:
        client.add_comment(task.id, f"Cleanup warning: failed to remove {repo}: {cleanup_error}")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select eligible yellow Kanboard tasks deterministically and dispatch opencode handler skills."
    )
    parser.add_argument("project_name", help="Exact Kanboard project name")
    parser.add_argument("--qa-duration", default=DEFAULT_QA_DURATION, help=f"QA duration for QA handler (default: {DEFAULT_QA_DURATION})")
    parser.add_argument("--ticket-lock-url", default=DEFAULT_TICKET_LOCK_URL, help=f"Ticket lock URL (default: {DEFAULT_TICKET_LOCK_URL})")
    parser.add_argument("--kanboard-url", default=DEFAULT_KANBOARD_URL, help=f"Kanboard base or JSON-RPC URL (default: {DEFAULT_KANBOARD_URL})")
    parser.add_argument("--kanboard-username", default=DEFAULT_KANBOARD_USERNAME, help=f"Kanboard API username (default: {DEFAULT_KANBOARD_USERNAME})")
    parser.add_argument("--kanboard-token-path", default=DEFAULT_TOKEN_PATH, help=f"Kanboard API token path (default: {DEFAULT_TOKEN_PATH})")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace containing plans/ and src/ (default: current directory)")
    parser.add_argument("--prompt-template", default=DEFAULT_TEMPLATE, help=f"Handler prompt template path (default: {DEFAULT_TEMPLATE})")
    parser.add_argument("--color-change-script", default=DEFAULT_COLOR_CHANGE_SCRIPT, help=f"Task color-change script path (default: {DEFAULT_COLOR_CHANGE_SCRIPT})")
    parser.add_argument("--opencode-bin", default="opencode", help="opencode executable path/name (default: opencode)")
    parser.add_argument("--model", help="Optional model passed to opencode run with -m")
    parser.add_argument("--opencode-arg", action="append", default=[], help="Extra argument passed to opencode run before the prompt; repeat as needed")
    parser.add_argument("--max-tasks", type=positive_int, default=1, help="Maximum handler tasks to run serially; 0 means until no unlocked eligible task remains (default: 1)")
    parser.add_argument("--run-dir", default=".autoloop/runs", help="Directory for rendered prompts and run metadata (default: .autoloop/runs)")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), help="Run id used under --run-dir")
    parser.add_argument("--dry-run", action="store_true", help="Render and print the selected handler prompt without running opencode")
    args = parser.parse_args(argv)

    if not VALID_QA_DURATION.match(args.qa_duration):
        parser.error("--qa-duration must be a positive integer followed by s, m, or h, such as 10s, 5m, or 3h")
    args.workspace = str(Path(args.workspace).resolve())
    return args


def orchestrate(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    ensure_workspace(workspace)

    client = KanboardClient(args.kanboard_url, args.kanboard_username, args.kanboard_token_path)
    project = client.find_project(args.project_name)
    project_id = int_field(project.get("id"), f"project id for {args.project_name}")
    columns = validate_columns(client.get_columns(project_id))

    handled = 0
    while args.max_tasks == 0 or handled < args.max_tasks:
        unlocked_purple = unlock_one_purple_task(args, client, project_id, columns)
        if unlocked_purple is not None:
            print(f"Unlocked purple task and marked yellow: {unlocked_purple}", flush=True)

        task, ignored, lock_taken, merge_locked = select_task(client, project_id, args.project_name, columns, args.ticket_lock_url)
        if ignored:
            print("Ignored tasks:", ", ".join(str(task_id) for task_id in ignored), flush=True)
        if lock_taken:
            print("Skipped locked tasks:", ", ".join(str(task_id) for task_id in lock_taken), flush=True)
        if merge_locked:
            print("Skipped merge-locked tasks:", ", ".join(str(task_id) for task_id in merge_locked), flush=True)
        if task is None:
            print("No available unlocked yellow work exists.", flush=True)
            return 0

        change_color(args, task.id, "green")
        remove_output_file(handler_output_path(args, task))

        if task.column.title == "Merging":
            try:
                refresh_workspace(args, client, task)
                handle_merging_task(args, client, project_id, columns, task)
            finally:
                if task.merge_lock_acquired:
                    release_project_merge_lock_best_effort(args)
            handled += 1
            if args.max_tasks != 0 and handled >= args.max_tasks:
                break
            time.sleep(0.2)
            continue

        refresh_workspace(args, client, task)

        handler_cwd = Path(args.workspace)
        extra_comments: list[str] = []
        wip_dir: Path | None = None
        qa_work_dir: Path | None = None
        plan_file = ""
        if task.column.title == "WIP":
            plan_file = resolve_plan_file_from_comments(args, client, task)
            try:
                wip_dir = prepare_wip_directory(args, task)
            except OrchestratorError as exc:
                mark_red_and_comment(args, client, task.id, str(exc))
                raise
            handler_cwd = wip_dir
        elif task.column.title == "QA":
            plan_file = resolve_plan_file_from_comments(args, client, task)
            try:
                qa_work_dir = prepare_qa_directory(args, task)
            except OrchestratorError as exc:
                mark_red_and_comment(args, client, task.id, str(exc))
                raise
            handler_cwd = qa_work_dir

        create_pending_output_file(args, task)
        prompt = render_prompt(args, task, plan_file=plan_file)
        write_run_files(args, task, prompt)
        run_handler(args, task, prompt, cwd=handler_cwd)
        output = read_handler_output(args, client, task)

        if output["status"] == "failure":
            handle_failure_output(args, client, task, output)
            if wip_dir is not None:
                cleanup_error = cleanup_directory(wip_dir)
                if cleanup_error:
                    client.add_comment(task.id, f"Cleanup warning: failed to remove {wip_dir}: {cleanup_error}")
            if qa_work_dir is not None:
                cleanup_error = cleanup_directory(qa_work_dir)
                if cleanup_error:
                    client.add_comment(task.id, f"Cleanup warning: failed to remove {qa_work_dir}: {cleanup_error}")
            handled += 1
            if args.max_tasks != 0 and handled >= args.max_tasks:
                break
            time.sleep(0.2)
            continue

        if task.column.title == "Plan":
            extra_comments.extend(commit_push_plan(args, client, task, output))
        elif task.column.title == "WIP":
            extra_comments.extend(commit_push_wip(args, client, task))

        advance_success(args, client, project_id, columns, task, output, extra_comments)
        if wip_dir is not None:
            cleanup_error = cleanup_directory(wip_dir)
            if cleanup_error:
                client.add_comment(task.id, f"Cleanup warning: failed to remove {wip_dir}: {cleanup_error}")
        if qa_work_dir is not None:
            cleanup_error = cleanup_directory(qa_work_dir)
            if cleanup_error:
                client.add_comment(task.id, f"Cleanup warning: failed to remove {qa_work_dir}: {cleanup_error}")
        handled += 1

        if args.max_tasks != 0 and handled >= args.max_tasks:
            break
        time.sleep(0.2)

    print(f"Handled {handled} task(s).", flush=True)
    return 0


def main(argv: list[str]) -> int:
    try:
        return orchestrate(parse_args(argv))
    except OrchestratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
