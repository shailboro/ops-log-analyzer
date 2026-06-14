from pydantic import BaseModel, Field

from app.graph.state import AgentState, DetectedIssue, Remediation, append_trace
from app.llm import get_llm


class RemediationOutput(BaseModel):
    remediations: list[Remediation] = Field(default_factory=list)


SYSTEM_PROMPT = """You are a Remediation agent for operations incidents.
For each detected issue, produce actionable fix steps, rationale, and optional rollback guidance.
Map each remediation to the issue_id. Steps should be ordered and specific to ops/SRE workflows.

If provided with similar past incidents, reference successful remediations from those cases.
Leverage historical context to provide faster, more reliable fixes.

Return structured JSON only."""


def remediation_node(state: AgentState) -> dict:
    issues: list[DetectedIssue] = state.get("issues", [])
    rag_context = state.get("rag_context", [])
    rag_insights = state.get("rag_insights", {})
    
    trace = append_trace(
        state.get("trace", []),
        "RemediationAgent",
        "started",
        f"Generating fixes for {len(issues)} issues",
    )

    if not issues:
        trace = append_trace(trace, "RemediationAgent", "skipped", "No issues to remediate")
        return {"remediations": [], "trace": trace}

    try:
        llm = get_llm().with_structured_output(RemediationOutput)
        
        # Build issue block
        issue_block = "\n".join(
            f"- {i.id} [{i.severity}] {i.title}: {i.summary}\n  Evidence: {'; '.join(i.evidence[:3])}"
            for i in issues
        )
        
        # Build RAG context block if available
        rag_block = ""
        if rag_context and rag_insights.get("mode") == "live":
            rag_block = "\n\n## Similar Past Incidents (from Knowledge Base):\n"
            for ctx in rag_context[:3]:  # Top 3 issues with similar incidents
                rag_block += f"\nFor issue {ctx['current_issue_id']} ({ctx['current_issue_title']}):\n"
                for similar in ctx.get("similar_incidents", [])[:2]:  # Top 2 similar
                    rag_block += f"  - Similar: {similar['title']} (severity: {similar['severity']}, match score: {similar['score']:.2f})\n"
                    rag_block += f"    Description: {similar['description'][:100]}...\n"
            
            # Add trend analysis
            trends = rag_insights.get("trends", {})
            if trends:
                rag_block += f"\n## 7-Day Trend Analysis:\n"
                rag_block += f"  Total incidents: {trends.get('total_issues', 0)}\n"
                for severity, count in trends.get('by_severity', {}).items():
                    rag_block += f"  - {severity}: {count}\n"
        
        user_message = f"Issues:\n{issue_block}"
        if rag_block:
            user_message += rag_block
        
        result: RemediationOutput = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )
        trace = append_trace(
            trace,
            "RemediationAgent",
            "completed",
            f"Generated {len(result.remediations)} remediation plans",
            artifact_keys=["remediations"],
        )
        return {"remediations": result.remediations, "trace": trace}
    except Exception as exc:
        trace = append_trace(trace, "RemediationAgent", "error", str(exc))
        return {"remediations": [], "trace": trace, "error": str(exc)}
