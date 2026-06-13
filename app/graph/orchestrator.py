from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.cookbook import cookbook_node
from app.agents.email_agent import email_node
from app.agents.jira_agent import jira_node
from app.agents.log_reader import log_reader_node
from app.agents.notification import notification_node
from app.agents.remediation import remediation_node
from app.config import get_settings
from app.graph.state import AgentState, initial_state
from app.services.run_store import run_store


def _fan_out_outputs(state: AgentState) -> list[Send]:
    """Parallel fan-out to Slack, JIRA, and Email after cookbook."""
    sends = [Send("notification", state)]
    critical = [i for i in state.get("issues", []) if i.severity.lower() in {"critical", "high"}]
    if critical:
        sends.append(Send("jira", state))
    sends.append(Send("email", state))
    return sends


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("log_reader", log_reader_node)
    graph.add_node("remediation", remediation_node)
    graph.add_node("cookbook", cookbook_node)
    graph.add_node("notification", notification_node)
    graph.add_node("email", email_node)
    graph.add_node("jira", jira_node)

    graph.add_edge(START, "log_reader")
    graph.add_edge("log_reader", "remediation")
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

    await run_store.complete_run(run_id, final_state)
    return final_state
