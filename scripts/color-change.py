#!/usr/bin/env python3
"""Change a Kanboard task color via JSON-RPC."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request


DEFAULT_KANBOARD_URL = "http://172.17.0.1:8080/"
DEFAULT_USERNAME = "admin"
DEFAULT_TOKEN_PATH = "/token"
VALID_COLORS = {"red", "yellow", "green"}


class KanboardError(RuntimeError):
    pass


def jsonrpc_url(base_url: str) -> str:
    if base_url.endswith("/jsonrpc.php"):
        return base_url
    return base_url.rstrip("/") + "/kanboard/jsonrpc.php"


def read_token(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as token_file:
            token = token_file.read().strip()
    except OSError as exc:
        raise KanboardError(f"failed to read token file {path!r}: {exc}") from exc

    if not token:
        raise KanboardError(f"token file {path!r} is empty")
    return token


def rpc_call(url: str, username: str, token: str, method: str, params: dict, request_id: int) -> object:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "id": request_id, "params": params}).encode(
        "utf-8"
    )
    auth = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise KanboardError(f"HTTP {exc.code} from Kanboard: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise KanboardError(f"Kanboard request failed: {exc}") from exc

    if "error" in payload:
        raise KanboardError(f"Kanboard JSON-RPC error for {method}: {payload['error']}")
    if "result" not in payload:
        raise KanboardError(f"Kanboard JSON-RPC response missing result for {method}: {payload}")
    return payload["result"]


def find_project(projects: object, project_name: str) -> dict:
    if not isinstance(projects, list):
        raise KanboardError(f"getAllProjects returned unexpected result: {projects!r}")

    matches = [project for project in projects if isinstance(project, dict) and project.get("name") == project_name]
    if not matches:
        raise KanboardError(f"project {project_name!r} was not found")
    if len(matches) > 1:
        raise KanboardError(f"project {project_name!r} matched more than once")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Change a Kanboard task color.")
    parser.add_argument("project_name", help="Exact Kanboard project name")
    parser.add_argument("ticket_id", type=int, help="Kanboard task/ticket id")
    parser.add_argument("color", help="Target color: red, yellow, or green")
    parser.add_argument("--kanboard-url", default=DEFAULT_KANBOARD_URL, help=f"Kanboard base or JSON-RPC URL (default: {DEFAULT_KANBOARD_URL})")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help=f"Kanboard API username (default: {DEFAULT_USERNAME})")
    parser.add_argument("--token-path", default=DEFAULT_TOKEN_PATH, help=f"API token file path (default: {DEFAULT_TOKEN_PATH})")
    args = parser.parse_args()

    color = args.color.lower()
    if color not in VALID_COLORS:
        print(f"error: color must be one of: {', '.join(sorted(VALID_COLORS))}", file=sys.stderr)
        return 2

    try:
        token = read_token(args.token_path)
        rpc_url = jsonrpc_url(args.kanboard_url)
        project = find_project(
            rpc_call(rpc_url, args.username, token, "getAllProjects", {}, 1), args.project_name
        )
        task = rpc_call(rpc_url, args.username, token, "getTask", {"task_id": args.ticket_id}, 2)
        if not isinstance(task, dict) or not task:
            raise KanboardError(f"task {args.ticket_id} was not found")

        if int(task.get("project_id", -1)) != int(project["id"]):
            raise KanboardError(
                f"task {args.ticket_id} belongs to project id {task.get('project_id')}, not {args.project_name!r}"
            )

        update_result = rpc_call(rpc_url, args.username, token, "updateTask", {"id": args.ticket_id, "color_id": color}, 3)
        if update_result is not True:
            raise KanboardError(f"updateTask did not return true: {update_result!r}")

        verified_task = rpc_call(rpc_url, args.username, token, "getTask", {"task_id": args.ticket_id}, 4)
        observed_color = verified_task.get("color_id") if isinstance(verified_task, dict) else None
        if observed_color != color:
            raise KanboardError(f"verification failed: observed color {observed_color!r}, expected {color!r}")
    except KanboardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Task {args.ticket_id} in project {args.project_name!r} changed to {color}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
