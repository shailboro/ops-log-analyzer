from typing import Any

from pydantic import BaseModel

from app.graph.state import AgentState, append_trace
from app.integrations.email import get_email_client
from app.llm import get_llm


class EmailPayloadOutput(BaseModel):
    subject: str
    body: str = ""
    html_body: str | None = None


SYSTEM_PROMPT = """You are an email notification agent summarizing ops log analysis.
Create a concise plain-text email with a subject, body, and optional html_body.
Include run ID, issue count, top severities, top 3 fixes, full JIRA ticket drafts, and a clear action recommendation.
Return JSON with subject, body, and html_body."""


def _format_jira_tickets(state: AgentState) -> str:
    jira_tickets = state.get("jira_tickets", [])
    if not jira_tickets:
        return ""

    ticket_texts = []
    for ticket in jira_tickets:
        ticket_texts.append(
            """
JIRA Ticket Draft
Issue ID: {issue_id}
Summary: {summary}
Description: {description}
Priority: {priority}
Issue Type: {issuetype}
""".strip().format(
                issue_id=ticket.get("issue_id", ""),
                summary=ticket.get("summary", ""),
                description=ticket.get("description", ""),
                priority=ticket.get("priority", ""),
                issuetype=ticket.get("issuetype", ""),
            )
        )
    return "\n\n".join(ticket_texts)


def _build_fallback_payload(state: AgentState) -> dict[str, Any]:
    issues = state.get("issues", [])
    jira_details = _format_jira_tickets(state)
    if not issues:
        body = f"Run ID: {state['run_id']}\n\nNo operational issues were detected."
        if jira_details:
            body += f"\n\n{jira_details}"
        return {
            "subject": f"Ops Log Analysis [{state['run_id']}] — all clear",
            "body": body,
        }

    lines = "\n".join(f"- [{issue.severity.upper()}] {issue.title}: {issue.summary}" for issue in issues[:5])
    body = f"Run ID: {state['run_id']}\n\nIssues:\n{lines}"
    if jira_details:
        body += f"\n\n{jira_details}"
    return {
        "subject": f"Ops Log Alert [{state['run_id']}] — {len(issues)} issues detected",
        "body": body,
    }


def _build_default_email_body(state: AgentState) -> str:
    issues = state.get("issues", [])
    issue_lines = "\n".join(f"- [{issue.severity.upper()}] {issue.title}: {issue.summary}" for issue in issues[:5])
    fix_lines = "\n".join(
        f"- {rem.issue_id}: {rem.fix_steps[0] if rem.fix_steps else 'See runbook'}"
        for rem in state.get("remediations", [])[:3]
    )
    jira_details = _format_jira_tickets(state)

    parts = [f"Run ID: {state['run_id']}\n"]
    if issue_lines:
        parts.append(f"Issues:\n{issue_lines}")
    else:
        parts.append("No operational issues were detected.")

    if fix_lines:
        parts.append(f"\nTop fixes:\n{fix_lines}")
    if jira_details:
        parts.append(f"\nJIRA Tickets:\n{jira_details}")
    return "\n\n".join(parts)


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
        jira_details = _format_jira_tickets(state)
        user_content = (
            f"Run ID: {state['run_id']}\n"
            f"Issues:\n{issue_summary or 'None'}\n\n"
            f"Top fixes:\n{fix_summary or 'N/A'}"
        )
        if jira_details:
            user_content += f"\n\nJIRA Tickets:\n{jira_details}"

        result: EmailPayloadOutput = get_llm().with_structured_output(EmailPayloadOutput).invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_content,
                },
            ]
        )
        body = result.body.strip() or _build_default_email_body(state)
        payload = {
            "subject": result.subject,
            "body": body,
            "html_body": result.html_body,
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
