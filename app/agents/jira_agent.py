from pydantic import BaseModel, Field

from app.graph.state import AgentState, DetectedIssue, append_trace
from app.integrations.jira import get_jira_client
from app.llm import get_llm

JIRA_SEVERITIES = {"critical", "high"}


class JiraTicketDraft(BaseModel):
    issue_id: str
    summary: str
    description: str
    priority: str = "High"
    issuetype: str = "Bug"


class JiraTicketsOutput(BaseModel):
    tickets: list[JiraTicketDraft] = Field(default_factory=list)


SYSTEM_PROMPT = """You are a JIRA Ticket agent for critical operational incidents.
Create JIRA ticket drafts for critical/high severity issues only.
Each ticket needs: issue_id, summary (<=80 chars), description (detailed), priority, issuetype.
Return structured JSON only."""


def _priority_for_severity(severity: str) -> str:
    return "Highest" if severity == "critical" else "High"


def jira_node(state: AgentState) -> dict:
    issues: list[DetectedIssue] = state.get("issues", [])
    critical_issues = [i for i in issues if i.severity.lower() in JIRA_SEVERITIES]
    trace = append_trace(
        state.get("trace", []),
        "JiraTicketAgent",
        "started",
        f"Evaluating {len(critical_issues)} critical/high issues for JIRA",
    )

    if not critical_issues:
        trace = append_trace(trace, "JiraTicketAgent", "skipped", "No critical/high issues — JIRA skipped")
        return {"jira_tickets": [], "jira_results": [], "trace": trace}

    tickets: list[dict] = []
    try:
        llm = get_llm().with_structured_output(JiraTicketsOutput)
        issue_block = "\n".join(
            f"- {i.id} [{i.severity}] {i.title}\n  {i.summary}\n  Evidence: {'; '.join(i.evidence[:3])}"
            for i in critical_issues
        )
        result: JiraTicketsOutput = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Run ID: {state['run_id']}\n\nIssues:\n{issue_block}"},
            ]
        )
        for draft in result.tickets:
            matching = next((i for i in critical_issues if i.id == draft.issue_id), None)
            severity = matching.severity if matching else "high"
            tickets.append(
                {
                    "issue_id": draft.issue_id,
                    "summary": draft.summary,
                    "description": draft.description,
                    "priority": draft.priority or _priority_for_severity(severity),
                    "issuetype": draft.issuetype,
                    "run_id": state["run_id"],
                }
            )
    except Exception:
        for issue in critical_issues:
            tickets.append(
                {
                    "issue_id": issue.id,
                    "summary": issue.title[:80],
                    "description": f"{issue.summary}\n\nEvidence:\n" + "\n".join(issue.evidence),
                    "priority": _priority_for_severity(issue.severity),
                    "issuetype": "Bug",
                    "run_id": state["run_id"],
                }
            )

    client = get_jira_client()
    results = [client.send(ticket, state["run_id"]) for ticket in tickets]
    mode = results[0].get("mode", "mock") if results else "mock"
    trace = append_trace(
        trace,
        "JiraTicketAgent",
        "completed",
        f"Created {len(tickets)} JIRA tickets ({mode} mode)",
        artifact_keys=["jira_tickets", "jira_results"],
    )
    return {"jira_tickets": tickets, "jira_results": results, "trace": trace}
