from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    timestamp: str | None = None
    level: str = "INFO"
    service: str | None = None
    message: str
    category: str = "unknown"
    extracted_fields: dict[str, str] = Field(default_factory=dict)


class DetectedIssue(BaseModel):
    id: str
    severity: str  # critical | high | medium | low
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    root_cause_hypothesis: str = ""


class Remediation(BaseModel):
    issue_id: str
    fix_steps: list[str] = Field(default_factory=list)
    rationale: str = ""
    rollback: str | None = None


class TraceEvent(BaseModel):
    agent: str
    status: str  # started | completed | skipped | error
    summary: str
    ts: str
    artifact_keys: list[str] = Field(default_factory=list)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_trace(
    trace: list[dict[str, Any]],
    agent: str,
    status: str,
    summary: str,
    artifact_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    event = TraceEvent(
        agent=agent,
        status=status,
        summary=summary,
        ts=utc_now_iso(),
        artifact_keys=artifact_keys or [],
    )
    return trace + [event.model_dump()]


def merge_trace(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return left + right


class AgentState(TypedDict):
    run_id: str
    raw_logs: str
    filename: str | None
    entries: list[LogEntry]
    issues: list[DetectedIssue]
    remediations: list[Remediation]
    cookbook_markdown: str
    slack_payloads: list[dict[str, Any]]
    jira_tickets: list[dict[str, Any]]
    slack_results: list[dict[str, Any]]
    jira_results: list[dict[str, Any]]
    trace: Annotated[list[dict[str, Any]], merge_trace]
    error: str | None


def initial_state(run_id: str, raw_logs: str, filename: str | None = None) -> AgentState:
    return AgentState(
        run_id=run_id,
        raw_logs=raw_logs,
        filename=filename,
        entries=[],
        issues=[],
        remediations=[],
        cookbook_markdown="",
        slack_payloads=[],
        jira_tickets=[],
        slack_results=[],
        jira_results=[],
        trace=[],
        error=None,
    )
