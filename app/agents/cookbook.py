from pydantic import BaseModel

from app.graph.state import AgentState, append_trace
from app.llm import get_llm


class CookbookOutput(BaseModel):
    cookbook_markdown: str


SYSTEM_PROMPT = """You are a Cookbook Synthesizer agent.
Merge detected issues and their remediations into one actionable markdown runbook/checklist.

Include sections:
1. Executive Summary
2. Prerequisites
3. Step-by-step Checklist (ordered, checkbox format using - [ ])
4. Verification Steps
5. Rollback Plan

Be concise but actionable for on-call engineers. Use markdown formatting."""


def cookbook_node(state: AgentState) -> dict:
    issues = state.get("issues", [])
    remediations = state.get("remediations", [])
    trace = append_trace(state.get("trace", []), "CookbookSynthesizer", "started", "Synthesizing runbook")

    if not issues:
        markdown = "# Ops Log Analysis — All Clear\n\nNo critical operational issues detected.\n"
        trace = append_trace(trace, "CookbookSynthesizer", "completed", "Generated all-clear runbook")
        return {"cookbook_markdown": markdown, "trace": trace}

    try:
        llm = get_llm().with_structured_output(CookbookOutput)
        issue_text = "\n".join(f"- [{i.severity}] {i.title}: {i.summary}" for i in issues)
        fix_text = "\n".join(
            f"- Issue {r.issue_id}: {r.rationale}\n  Steps: {'; '.join(r.fix_steps)}"
            for r in remediations
        )
        result: CookbookOutput = llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Run ID: {state['run_id']}\n\nIssues:\n{issue_text}\n\nRemediations:\n{fix_text}",
                },
            ]
        )
        trace = append_trace(
            trace,
            "CookbookSynthesizer",
            "completed",
            "Runbook checklist synthesized",
            artifact_keys=["cookbook_markdown"],
        )
        return {"cookbook_markdown": result.cookbook_markdown, "trace": trace}
    except Exception as exc:
        trace = append_trace(trace, "CookbookSynthesizer", "error", str(exc))
        fallback = "# Ops Log Runbook\n\nAnalysis encountered an error generating the full cookbook.\n"
        return {"cookbook_markdown": fallback, "trace": trace, "error": str(exc)}
