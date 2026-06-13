from pydantic import BaseModel, Field

from app.graph.state import AgentState, DetectedIssue, LogEntry, append_trace
from app.llm import get_llm
from app.parsers.log_parser import entries_to_prompt_block, preparse_logs


class ClassifiedEntry(BaseModel):
    index: int
    category: str
    extracted_fields: dict[str, str] = Field(default_factory=dict)


class LogReaderOutput(BaseModel):
    entries: list[ClassifiedEntry]
    issues: list[DetectedIssue]


SYSTEM_PROMPT = """You are a Log Reader and Classifier agent for operations logs.
Given pre-parsed log entries, assign each entry a category and extract useful fields.
Categories: auth, db, network, resource, config, deployment, unknown.

Also detect distinct operational issues grouped by pattern. For each issue provide:
- id (short slug like issue-1)
- severity: critical | high | medium | low
- title, summary, evidence (raw log lines), root_cause_hypothesis

Focus on ERROR/FATAL/WARN patterns and recurring failures. Merge duplicate patterns.
Return structured JSON only."""


def log_reader_node(state: AgentState) -> dict:
    trace = append_trace(state.get("trace", []), "LogReaderClassifier", "started", "Parsing and classifying logs")
    try:
        parsed = preparse_logs(state["raw_logs"])
        if not parsed:
            trace = append_trace(trace, "LogReaderClassifier", "completed", "No log lines found")
            return {"entries": [], "issues": [], "trace": trace}

        llm = get_llm().with_structured_output(LogReaderOutput)
        prompt = f"""Pre-parsed entries ({len(parsed)} lines):
{entries_to_prompt_block(parsed)}

For each entry index (0-based), set category and extracted_fields.
Detect operational issues from the full log set."""

        # Build index map for merging LLM classifications back
        entry_lines = "\n".join(
            f"{i}: [{e.timestamp or '?'}] {e.level} {e.service or '?'}: {e.message}"
            for i, e in enumerate(parsed[:150])
        )
        result: LogReaderOutput = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt + "\n\nIndexed entries:\n" + entry_lines},
            ]
        )

        enriched: list[LogEntry] = []
        classification_map = {c.index: c for c in result.entries}
        for i, entry in enumerate(parsed):
            classified = classification_map.get(i)
            if classified:
                enriched.append(
                    entry.model_copy(
                        update={
                            "category": classified.category,
                            "extracted_fields": classified.extracted_fields,
                        }
                    )
                )
            else:
                enriched.append(entry)

        summary = f"Parsed {len(enriched)} entries, detected {len(result.issues)} issues"
        trace = append_trace(
            trace,
            "LogReaderClassifier",
            "completed",
            summary,
            artifact_keys=["entries", "issues"],
        )
        return {"entries": enriched, "issues": result.issues, "trace": trace}
    except Exception as exc:
        trace = append_trace(trace, "LogReaderClassifier", "error", str(exc))
        parsed = preparse_logs(state["raw_logs"])
        error_lines = [e for e in parsed if e.level in {"ERROR", "FATAL", "CRITICAL"}]
        fallback_issues: list[DetectedIssue] = []
        if error_lines:
            fallback_issues.append(
                DetectedIssue(
                    id="issue-1",
                    severity="high",
                    title="Error events detected",
                    summary=f"Found {len(error_lines)} error-level log entries",
                    evidence=[f"{e.level}: {e.message}" for e in error_lines[:5]],
                    root_cause_hypothesis="Multiple error events require investigation",
                )
            )
        return {
            "entries": parsed,
            "issues": fallback_issues,
            "trace": trace,
            "error": str(exc),
        }
