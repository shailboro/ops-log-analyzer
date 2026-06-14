from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.cookbook import cookbook_node
from app.agents.email_agent import email_node
from app.agents.jira_agent import jira_node
from app.agents.log_reader import log_reader_node
from app.agents.notification import notification_node
from app.agents.rag_agent import rag_agent
from app.agents.remediation import remediation_node
from app.config import get_settings
from app.graph.state import AgentState, initial_state
from app.services.run_store import run_store

try:
    from app.rag import embed_issue, upsert_incident
    HAS_RAG = True
except ImportError:
    HAS_RAG = False


def _fan_out_outputs(state: AgentState) -> list[Send]:
    """Parallel fan-out to Slack, JIRA, and Email after cookbook."""
    sends = [Send("notification", state)]
    critical = [i for i in state.get("issues", []) if i.severity.lower() in {"critical", "high"}]
    if critical:
        sends.append(Send("jira", state))
    sends.append(Send("email", state))
    return sends


async def _store_incidents_in_rag(run_id: str, state: AgentState) -> dict[str, Any]:
    """
    Store analyzed incidents in Pinecone RAG for future retrieval.

    Returns storage summary with counts and any errors encountered.
    """
    if not HAS_RAG:
        return {"mode": "disabled", "reason": "RAG module unavailable"}

    settings = get_settings()
    if not settings.rag_configured:
        return {"mode": "disabled", "reason": "PINECONE_API_KEY or PINECONE_INDEX_NAME not set"}

    if not settings.llm_configured:
        return {
            "mode": "disabled",
            "reason": "OPENROUTER_API_KEY required to generate embeddings before storage",
        }

    issues = state.get("issues", [])
    remediations = state.get("remediations", [])

    if not issues:
        return {"mode": "live", "stored_count": 0, "failed_count": 0, "errors": []}

    remediation_map = {r.issue_id: r for r in remediations}
    stored_count = 0
    failed_count = 0
    errors: list[str] = []

    for issue in issues:
        try:
            embedding = await embed_issue(
                {
                    "id": issue.id,
                    "title": issue.title,
                    "description": issue.summary,
                    "severity": issue.severity,
                }
            )

            remediation = remediation_map.get(issue.id)
            remediation_text = None
            if remediation:
                remediation_text = (
                    f"Fix steps: {', '.join(remediation.fix_steps)}. "
                    f"Rationale: {remediation.rationale}"
                )

            stored = await upsert_incident(
                run_id=run_id,
                issue_id=issue.id,
                embedding=embedding,
                issue_data={
                    "title": issue.title,
                    "description": issue.summary,
                    "severity": issue.severity,
                },
                remediation=remediation_text,
            )
            if stored:
                stored_count += 1
            else:
                failed_count += 1
                errors.append(f"{issue.id}: upsert returned false")
        except Exception as exc:
            failed_count += 1
            message = f"{issue.id}: {exc}"
            errors.append(message)
            print(f"Error storing incident {issue.id} in RAG: {exc}")

    return {
        "mode": "live",
        "stored_count": stored_count,
        "failed_count": failed_count,
        "errors": errors[:5],
    }


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("log_reader", log_reader_node)
    graph.add_node("rag", rag_agent)
    graph.add_node("remediation", remediation_node)
    graph.add_node("cookbook", cookbook_node)
    graph.add_node("notification", notification_node)
    graph.add_node("email", email_node)
    graph.add_node("jira", jira_node)

    graph.add_edge(START, "log_reader")
    graph.add_edge("log_reader", "rag")
    graph.add_edge("rag", "remediation")
    graph.add_edge("remediation", "cookbook")
    graph.add_conditional_edges("cookbook", _fan_out_outputs, ["notification", "jira", "email"])
    graph.add_edge("notification", END)
    graph.add_edge("email", END)
    graph.add_edge("jira", END)

    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_analysis(run_id: str, raw_logs: str, filename: str | None = None) -> AgentState:
    settings = get_settings()
    if len(raw_logs.encode("utf-8")) > settings.max_log_bytes:
        raise ValueError(f"Log exceeds maximum size of {settings.max_log_bytes} bytes")

    state = initial_state(run_id, raw_logs, filename)

    graph = get_graph()

    # Stream graph execution and emit trace events
    final_state: AgentState | None = None
    seen_events = 0

    async for event in graph.astream(state, stream_mode="values"):
        final_state = event
        trace = event.get("trace", [])
        for entry in trace[seen_events:]:
            await run_store.append_event(run_id, entry)
        seen_events = len(trace)

    if final_state is None:
        raise RuntimeError("Graph produced no output")

    try:
        storage_result = await _store_incidents_in_rag(run_id, final_state)
        final_state["rag_insights"] = {
            **final_state.get("rag_insights", {}),
            "storage": storage_result,
        }
    except Exception as exc:
        print(f"Warning: Failed to store incidents in RAG: {exc}")
        final_state["rag_insights"] = {
            **final_state.get("rag_insights", {}),
            "storage": {"mode": "error", "error": str(exc)},
        }

    await run_store.complete_run(run_id, final_state)
    return final_state
