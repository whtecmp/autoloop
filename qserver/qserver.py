#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import threading
from pathlib import Path


TAKEN_MISSIONS_FILE = Path("taken-missions")
REQUEST_LOCK = threading.Lock()


class MissionRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        with REQUEST_LOCK:
            if self.path == "/can-merge-now":
                self._handle_can_merge_now()
                return
            if self.path == "/done-merging":
                self._handle_done_merging()
                return
            if self.path == "/take-lock":
                self._handle_mission_claim()
                return
            if self.path == "/remove-ticket-lock":
                self._handle_remove_ticket_lock()
                return

            self._send_text(404, "not found")

    def _handle_mission_claim(self):
        try:
            mission = self._read_mission_from_body()
        except (json.JSONDecodeError, KeyError):
            self._send_text(400, "bad request")
            return

        taken_missions = self._read_taken_missions()

        if mission in taken_missions:
            self._send_text(200, "taken")
            return

        self._append_taken_mission(mission)
        self._send_text(200, "ok")

    def _handle_remove_ticket_lock(self):
        try:
            mission = self._read_mission_from_body()
        except (json.JSONDecodeError, KeyError):
            self._send_text(400, "bad request")
            return

        taken_missions = self._read_taken_missions()
        taken_missions.discard(mission)
        self._write_taken_missions(taken_missions)
        self._send_text(200, "ok")

    def _handle_can_merge_now(self):
        try:
            project_name = self._read_json_body()
            lock_file = self._project_lock_file(project_name)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._send_text(400, "bad request")
            return

        try:
            with lock_file.open("x", encoding="utf-8") as project_lock:
                project_lock.write("")
        except FileExistsError:
            self._send_text(200, "no")
            return

        self._send_text(200, "yes")

    def _handle_done_merging(self):
        try:
            project_name = self._read_json_body()
            lock_file = self._project_lock_file(project_name)
            lock_file.unlink(missing_ok=True)
        except (json.JSONDecodeError, TypeError, ValueError, OSError):
            pass

        self._send_text(200, "ok")

    def _project_lock_file(self, project_name):
        if not isinstance(project_name, str) or not project_name:
            raise ValueError("project name must be a non-empty string")
        if project_name in (".", "..") or "/" in project_name or "\\" in project_name:
            raise ValueError("project name must be a file name, not a path")

        return Path(f"{project_name}.lock")

    def do_GET(self):
        self._send_text(405, "method not allowed")

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        return json.loads(raw_body.decode("utf-8"))

    def _read_mission_from_body(self):
        request = self._read_json_body()
        return (
            str(request["requested-ticket-id"]),
            str(request["current-column"]),
            str(request["project-name"]),
        )

    def _read_taken_missions(self):
        if not TAKEN_MISSIONS_FILE.exists():
            return set()

        taken_missions = set()
        for line in TAKEN_MISSIONS_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            taken_missions.add((
                record["requested-ticket-id"],
                record["current-column"],
                record.get("project-name"),
            ))
        return taken_missions

    def _append_taken_mission(self, mission):
        TAKEN_MISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "requested-ticket-id": mission[0],
            "current-column": mission[1],
            "project-name": mission[2],
        }
        with TAKEN_MISSIONS_FILE.open("a", encoding="utf-8") as missions_file:
            missions_file.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _write_taken_missions(self, missions):
        TAKEN_MISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TAKEN_MISSIONS_FILE.open("w", encoding="utf-8") as missions_file:
            for mission in sorted(missions):
                record = {
                    "requested-ticket-id": mission[0],
                    "current-column": mission[1],
                    "project-name": mission[2],
                }
                missions_file.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _send_text(self, status_code, body):
        encoded_body = body.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_body)))
        self.end_headers()
        self.wfile.write(encoded_body)

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="Mission claiming HTTP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MissionRequestHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
