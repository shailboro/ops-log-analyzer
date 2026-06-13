from pydantic import BaseModel, Field

from app.graph.state import AgentState, append_trace
from app.integrations.slack import get_slack_client
from app.llm import get_llm


class SlackMessageOutput(BaseModel):
    text: str
    blocks: list[dict] = Field(default_factory=list)


SYSTEM_PROMPT = """You are a Notification agent formatting ops incident summaries for Slack.
Create a concise Slack message with Block Kit blocks (header, section, divider).
Include: run ID, issue count, top severities, top 3 fixes, and a call to action.
Return JSON with 'text' (fallback) and 'blocks' (Slack Block Kit array)."""


def _build_fallback_payload(state: AgentState) -> dict:
    issues = state.get("issues", [])
    if not issues:
        return {
            "text": f"Ops Log Analysis [{state['run_id']}]: All clear — no issues detected.",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": "Ops Log Analysis — All Clear"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Run ID:* `{state['run_id']}`\nNo operational issues detected.",
                    },
                },
            ],
        }

    top = issues[:3]
    lines = "\n".join(f"• [{i.severity.upper()}] {i.title}" for i in top)
    return {
        "text": f"Ops Log Analysis [{state['run_id']}]: {len(issues)} issues detected",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Ops Log Analysis Alert"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Run ID:* `{state['run_id']}`\n*Issues:* {len(issues)}\n{lines}",
                },
            },
        ],
    }


def notification_node(state: AgentState) -> dict:
    trace = append_trace(state.get("trace", []), "NotificationAgent", "started", "Building Slack notification")
    try:
        llm = get_llm().with_structured_output(SlackMessageOutput)
        issue_summary = "\n".join(
            f"- [{i.severity}] {i.title}: {i.summary}" for i in state.get("issues", [])[:5]
        )
        fix_summary = "\n".join(
            f"- {r.issue_id}: {r.fix_steps[0] if r.fix_steps else 'See runbook'}"
            for r in state.get("remediations", [])[:3]
        )
        result: SlackMessageOutput = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Run ID: {state['run_id']}\n"
                        f"Issues:\n{issue_summary or 'None'}\n"
                        f"Top fixes:\n{fix_summary or 'N/A'}"
                    ),
                },
            ]
        )
        payload = {"text": result.text, "blocks": result.blocks}
    except Exception:
        payload = _build_fallback_payload(state)

    client = get_slack_client()
    send_result = client.send(payload, state["run_id"])
    mode = send_result.get("mode", "mock")
    trace = append_trace(
        trace,
        "NotificationAgent",
        "completed",
        f"Slack notification sent ({mode} mode)",
        artifact_keys=["slack_payloads", "slack_results"],
    )
    return {
        "slack_payloads": [payload],
        "slack_results": [send_result],
        "trace": trace,
    }
