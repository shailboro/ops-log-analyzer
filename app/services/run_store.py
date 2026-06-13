import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.graph.state import AgentState


@dataclass
class RunRecord:
    run_id: str
    status: str = "pending"
    state: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self.settings = get_settings()

    async def create_run(self, run_id: str, raw_logs: str, filename: str | None = None) -> RunRecord:
        async with self._lock:
            record = RunRecord(
                run_id=run_id,
                status="running",
                state={
                    "run_id": run_id,
                    "filename": filename,
                    "raw_log_lines": len(raw_logs.splitlines()),
                },
            )
            self._runs[run_id] = record
            self._persist_record(record)
            return record

    async def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            record = self._require(run_id)
            record.events.append(event)
            self._persist_record(record)

    async def complete_run(self, run_id: str, state: AgentState) -> None:
        async with self._lock:
            record = self._require(run_id)
            record.status = "completed"
            record.state = self._serialize_state(state)
            self._persist_record(record)
            self._persist_artifact(run_id, record.state)

    async def fail_run(self, run_id: str, error: str, partial_state: dict[str, Any] | None = None) -> None:
        async with self._lock:
            record = self._require(run_id)
            record.status = "failed"
            record.error = error
            if partial_state:
                record.state = partial_state
            self._persist_record(record)

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._lock:
            record = self._runs.get(run_id)
            if record:
                return record
            return self._load_record(run_id)

    def _require(self, run_id: str) -> RunRecord:
        record = self._runs.get(run_id)
        if not record:
            raise KeyError(f"Run {run_id} not found")
        return record

    def _serialize_state(self, state: AgentState) -> dict[str, Any]:
        return {
            "run_id": state["run_id"],
            "filename": state.get("filename"),
            "entries": [e.model_dump() for e in state.get("entries", [])],
            "issues": [i.model_dump() for i in state.get("issues", [])],
            "remediations": [r.model_dump() for r in state.get("remediations", [])],
            "cookbook_markdown": state.get("cookbook_markdown", ""),
            "slack_payloads": state.get("slack_payloads", []),
            "jira_tickets": state.get("jira_tickets", []),
            "slack_results": state.get("slack_results", []),
            "jira_results": state.get("jira_results", []),
            "trace": state.get("trace", []),
            "error": state.get("error"),
        }

    def _record_path(self, run_id: str) -> Path:
        return Path(self.settings.runs_dir) / run_id / "record.json"

    def _persist_record(self, record: RunRecord) -> None:
        path = self._record_path(record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": record.run_id,
            "status": record.status,
            "state": record.state,
            "events": record.events,
            "error": record.error,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_record(self, run_id: str) -> RunRecord | None:
        path = self._record_path(run_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = RunRecord(
            run_id=payload["run_id"],
            status=payload.get("status", "pending"),
            state=payload.get("state", {}),
            events=payload.get("events", []),
            error=payload.get("error"),
        )
        self._runs[run_id] = record
        return record

    def _persist_artifact(self, run_id: str, state: dict[str, Any]) -> None:
        runs_dir = Path(self.settings.runs_dir) / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


run_store = RunStore()
