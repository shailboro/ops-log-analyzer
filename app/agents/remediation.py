from pydantic import BaseModel, Field

from app.graph.state import AgentState, DetectedIssue, Remediation, append_trace
from app.llm import get_llm


class RemediationOutput(BaseModel):
    remediations: list[Remediation] = Field(default_factory=list)


SYSTEM_PROMPT = """You are a Remediation agent for operations incidents.
For each detected issue, produce actionable fix steps, rationale, and optional rollback guidance.
Map each remediation to the issue_id. Steps should be ordered and specific to ops/SRE workflows.
Return structured JSON only."""


def remediation_node(state: AgentState) -> dict:
    issues: list[DetectedIssue] = state.get("issues", [])
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
        issue_block = "\n".join(
            f"- {i.id} [{i.severity}] {i.title}: {i.summary}\n  Evidence: {'; '.join(i.evidence[:3])}"
            for i in issues
        )
        result: RemediationOutput = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Issues:\n{issue_block}"},
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
