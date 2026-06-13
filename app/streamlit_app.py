import time
from pathlib import Path

import httpx
import streamlit as st

from app.config import get_settings

st.set_page_config(page_title="Ops Log Analyzer", page_icon="📋", layout="wide")

SEVERITY_COLORS = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}

AGENT_ORDER = [
    "LogReaderClassifier",
    "RemediationAgent",
    "CookbookSynthesizer",
    "NotificationAgent",
    "JiraTicketAgent",
]


def severity_badge(severity: str) -> str:
    icon = SEVERITY_COLORS.get(severity.lower(), "⚪")
    return f"{icon} {severity.upper()}"


def load_sample(name: str) -> str:
    path = Path("samples") / name
    return path.read_text(encoding="utf-8")


def start_analysis(logs: str, filename: str | None) -> str | None:
    settings = get_settings()
    try:
        response = httpx.post(
            f"{settings.api_base_url}/analyze",
            json={"logs": logs, "filename": filename},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["run_id"]
    except httpx.HTTPError as exc:
        st.error(f"Failed to start analysis: {exc}")
        return None


def fetch_run(run_id: str) -> dict | None:
    settings = get_settings()
    try:
        response = httpx.get(f"{settings.api_base_url}/runs/{run_id}", timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return None


def render_trace(events: list[dict]) -> None:
    seen_agents = {e.get("agent") for e in events}
    for agent in AGENT_ORDER:
        agent_events = [e for e in events if e.get("agent") == agent]
        if not agent_events:
            st.markdown(f"⬜ **{agent}** — pending")
            continue
        latest = agent_events[-1]
        status = latest.get("status", "")
        icon = {"completed": "✅", "started": "🔄", "skipped": "⏭️", "error": "❌"}.get(status, "•")
        st.markdown(f"{icon} **{agent}** — {latest.get('summary', '')}")
        st.caption(latest.get("ts", ""))


def render_findings(state: dict) -> None:
    issues = state.get("issues", [])
    if not issues:
        st.success("No operational issues detected.")
        return
    for issue in issues:
        with st.expander(f"{severity_badge(issue['severity'])} {issue['title']}", expanded=True):
            st.write(issue.get("summary", ""))
            st.markdown(f"**Root cause hypothesis:** {issue.get('root_cause_hypothesis', 'N/A')}")
            if issue.get("evidence"):
                st.markdown("**Evidence:**")
                for line in issue["evidence"]:
                    st.code(line)


def render_fixes(state: dict) -> None:
    remediations = state.get("remediations", [])
    issues = {i["id"]: i for i in state.get("issues", [])}
    if not remediations:
        st.info("No remediations generated.")
        return
    for rem in remediations:
        issue = issues.get(rem["issue_id"], {})
        title = issue.get("title", rem["issue_id"])
        st.subheader(title)
        st.write(rem.get("rationale", ""))
        for i, step in enumerate(rem.get("fix_steps", []), 1):
            st.markdown(f"{i}. {step}")
        if rem.get("rollback"):
            st.markdown(f"**Rollback:** {rem['rollback']}")
        st.divider()


def render_outputs(state: dict) -> None:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Slack")
        results = state.get("slack_results", [])
        mode = results[0].get("mode", "mock") if results else "mock"
        st.caption(f"Mode: **{mode}**")
        for payload in state.get("slack_payloads", []):
            st.json(payload)
    with col2:
        st.subheader("JIRA")
        results = state.get("jira_results", [])
        if not state.get("jira_tickets"):
            st.info("No JIRA tickets (no critical/high issues or skipped).")
        else:
            mode = results[0].get("mode", "mock") if results else "mock"
            st.caption(f"Mode: **{mode}**")
            for ticket in state.get("jira_tickets", []):
                st.json(ticket)


def main() -> None:
    settings = get_settings()
    st.title("Ops Log Analyzer")
    st.caption("Multi-agent log analysis with LangGraph — upload ops logs for live classification, fixes, and actionable output.")

    if "run_id" not in st.session_state:
        st.session_state.run_id = None
    if "run_data" not in st.session_state:
        st.session_state.run_data = None

    with st.sidebar:
        st.header("Configuration")
        st.write(f"API: `{settings.api_base_url}`")
        st.write(f"LLM: `{settings.llm_provider}` ({'configured' if settings.llm_configured else 'missing key'})")
        st.write(f"Slack: {'live' if settings.slack_configured else 'mock'}")
        st.write(f"JIRA: {'live' if settings.jira_configured else 'mock'}")
        st.divider()
        st.subheader("Sample logs")
        if st.button("Load k8s_crashloop.log"):
            st.session_state.sample_logs = load_sample("k8s_crashloop.log")
            st.session_state.sample_name = "k8s_crashloop.log"
        if st.button("Load db_connection.log"):
            st.session_state.sample_logs = load_sample("db_connection.log")
            st.session_state.sample_name = "db_connection.log"
        if st.button("Load healthy_with_warnings.log"):
            st.session_state.sample_logs = load_sample("healthy_with_warnings.log")
            st.session_state.sample_name = "healthy_with_warnings.log"

    tab_upload, tab_trace, tab_findings, tab_fixes, tab_cookbook, tab_outputs = st.tabs(
        ["Upload", "Live Trace", "Findings", "Fixes", "Cookbook", "Outputs"]
    )

    with tab_upload:
        uploaded = st.file_uploader("Upload log file", type=["log", "txt"])
        default_text = st.session_state.get("sample_logs", "")
        logs = st.text_area("Or paste logs", value=default_text, height=300)
        filename = None

        if uploaded:
            logs = uploaded.read().decode("utf-8", errors="replace")
            filename = uploaded.name
        elif st.session_state.get("sample_name"):
            filename = st.session_state.sample_name

        if st.button("Analyze", type="primary", disabled=not logs.strip()):
            run_id = start_analysis(logs, filename)
            if run_id:
                st.session_state.run_id = run_id
                st.session_state.run_data = None
                st.success(f"Analysis started — run ID: `{run_id}`")

    run_id = st.session_state.run_id
    if run_id:
        with tab_trace:
            st.subheader(f"Run `{run_id}`")
            placeholder = st.empty()
            max_wait = 120
            elapsed = 0
            while elapsed < max_wait:
                run_data = fetch_run(run_id)
                if run_data:
                    st.session_state.run_data = run_data
                    with placeholder.container():
                        render_trace(run_data.get("events", []))
                    if run_data.get("status") in {"completed", "failed"}:
                        if run_data.get("status") == "failed":
                            st.error(run_data.get("error", "Analysis failed"))
                        break
                time.sleep(1)
                elapsed += 1

        run_data = st.session_state.run_data
        if run_data and run_data.get("state"):
            state = run_data["state"]
            with tab_findings:
                render_findings(state)
            with tab_fixes:
                render_fixes(state)
            with tab_cookbook:
                md = state.get("cookbook_markdown", "")
                st.markdown(md)
                st.download_button("Copy as .md", md, file_name=f"runbook-{run_id}.md")
            with tab_outputs:
                render_outputs(state)
    else:
        for tab in [tab_trace, tab_findings, tab_fixes, tab_cookbook, tab_outputs]:
            with tab:
                st.info("Upload or paste logs and click Analyze to begin.")


if __name__ == "__main__":
    main()
