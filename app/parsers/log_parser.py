import json
import re
from typing import Iterator

from app.graph.state import LogEntry

ISO8601_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
)
SYSLOG_PREFIX = re.compile(
    r"^(?P<ts>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(?P<host>\S+)\s+"
)
LEVEL_BRACKET = re.compile(r"\[(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\]", re.I)
LEVEL_WORD = re.compile(
    r"\b(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b",
    re.I,
)
SERVICE_PREFIX = re.compile(r"^(?P<service>[\w.-]+):\s+", re.I)


def split_log_lines(raw_logs: str) -> list[str]:
    return [line.rstrip("\r") for line in raw_logs.splitlines() if line.strip()]


def chunk_lines(lines: list[str], chunk_size: int = 200) -> Iterator[list[str]]:
    for i in range(0, len(lines), chunk_size):
        yield lines[i : i + chunk_size]


def _normalize_level(level: str) -> str:
    upper = level.upper()
    if upper == "WARNING":
        return "WARN"
    return upper


def _parse_json_line(line: str) -> LogEntry | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    message = str(data.get("message") or data.get("msg") or data.get("log") or line)
    level = _normalize_level(str(data.get("level") or data.get("severity") or "INFO"))
    timestamp = data.get("timestamp") or data.get("time") or data.get("@timestamp")
    service = data.get("service") or data.get("logger") or data.get("component")

    extracted = {
        k: str(v)
        for k, v in data.items()
        if k not in {"message", "msg", "log", "level", "severity", "timestamp", "time", "@timestamp", "service", "logger", "component"}
        and v is not None
    }

    return LogEntry(
        timestamp=str(timestamp) if timestamp else None,
        level=level,
        service=str(service) if service else None,
        message=message,
        category="unknown",
        extracted_fields=extracted,
    )


def _parse_structured_line(line: str) -> LogEntry:
    json_entry = _parse_json_line(line)
    if json_entry:
        return json_entry

    timestamp: str | None = None
    service: str | None = None
    remainder = line

    iso_match = ISO8601_PREFIX.match(line)
    if iso_match:
        timestamp = iso_match.group("ts")
        remainder = line[iso_match.end() :]
    else:
        syslog_match = SYSLOG_PREFIX.match(line)
        if syslog_match:
            timestamp = syslog_match.group("ts")
            service = syslog_match.group("host")
            remainder = line[syslog_match.end() :]

    level = "INFO"
    bracket_match = LEVEL_BRACKET.search(remainder)
    if bracket_match:
        level = _normalize_level(bracket_match.group("level"))
    else:
        word_match = LEVEL_WORD.search(remainder)
        if word_match:
            level = _normalize_level(word_match.group("level"))

    service_match = SERVICE_PREFIX.match(remainder)
    if service_match and not service:
        service = service_match.group("service")
        remainder = remainder[service_match.end() :]

    return LogEntry(
        timestamp=timestamp,
        level=level,
        service=service,
        message=remainder.strip() or line,
        category="unknown",
        extracted_fields={},
    )


def preparse_logs(raw_logs: str) -> list[LogEntry]:
    return [_parse_structured_line(line) for line in split_log_lines(raw_logs)]


def entries_to_prompt_block(entries: list[LogEntry], max_entries: int = 150) -> str:
    lines: list[str] = []
    for entry in entries[:max_entries]:
        ts = entry.timestamp or "?"
        svc = entry.service or "unknown"
        lines.append(f"[{ts}] {entry.level} {svc}: {entry.message}")
    if len(entries) > max_entries:
        lines.append(f"... ({len(entries) - max_entries} more entries truncated)")
    return "\n".join(lines)
