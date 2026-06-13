from typing import Any

from app.graph.state import AgentState, append_trace
from app.integrations.email import get_email_client
from app.llm import get_llm


SYSTEM_PROMPT = """You are an email notification agent summarizing ops log analysis.
Create a concise plain-text email with a subject, body, and optional html_body.
Include run ID, issue count, top severities, top 3 fixes, and a clear action recommendation.
Return JSON with subject, body, and html_body."""


def _build_fallback_payload(state: AgentState) -> dict[str, Any]:
    issues = state.get("issues", [])
    if not issues:
        return {
            "subject": f"Ops Log Analysis [{state['run_id']}] — all clear",
            "body": f"Run ID: {state['run_id']}\n\nNo operational issues were detected.",
        }

    lines = "\n".join(f"- [{issue.severity.upper()}] {issue.title}: {issue.summary}" for issue in issues[:5])
    return {
        "subject": f"Ops Log Alert [{state['run_id']}] — {len(issues)} issues detected",
        "body": f"Run ID: {state['run_id']}\n\nIssues:\n{lines}",
    }


def email_node(state: AgentState) -> dict[str, Any]:
    trace = append_trace(state.get("trace", []), "EmailNotificationAgent", "started", "Building email notification")
    try:
        llm = get_llm()
        issue_summary = "\n".join(
            f"- [{issue.severity}] {issue.title}: {issue.summary}" for issue in state.get("issues", [])[:5]
        )
        fix_summary = "\n".join(
            f"- {rem.issue_id}: {rem.fix_steps[0] if rem.fix_steps else 'See runbook'}"
            for rem in state.get("remediations", [])[:3]
        )
        result = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Run ID: {state['run_id']}\n"
                        f"Issues:\n{issue_summary or 'None'}\n\n"
                        f"Top fixes:\n{fix_summary or 'N/A'}"
                    ),
                },
            ]
        )
        payload = {
            "subject": getattr(result, "subject", f"Ops Log Alert [{state['run_id']} ]"),
            "body": getattr(result, "body", ""),
            "html_body": getattr(result, "html_body", None),
        }
    except Exception:
        payload = _build_fallback_payload(state)

    client = get_email_client()
    send_result = client.send(payload, state["run_id"])
    mode = send_result.get("mode", "mock")
    trace = append_trace(
        trace,
        "EmailNotificationAgent",
        "completed",
        f"Email notification sent ({mode} mode)",
        artifact_keys=["email_payloads", "email_results"],
    )
    return {
        "email_payloads": [payload],
        "email_results": [send_result],
        "trace": trace,
    }
