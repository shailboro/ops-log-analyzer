"""RAG Agent - Retrieves similar past incidents and trend analysis for context."""

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.types import Send

from app.config import get_settings
from app.graph.state import AgentState, DetectedIssue
from app.rag import embed_issue, query_similar_incidents, query_trend_analysis


async def rag_agent(state: AgentState) -> dict[str, Any]:
    """
    RAG agent that retrieves similar past incidents and trend analysis.
    
    Uses embeddings to find similar issues from Pinecone and provides
    context about recurring patterns.
    
    Args:
        state: Current analysis state
        
    Returns:
        Dict with 'rag_context' and 'rag_insights'
    """
    settings = get_settings()
    
    if not settings.rag_configured:
        return {
            "rag_context": [],
            "rag_insights": {
                "mode": "mock",
                "message": "RAG not configured (no PINECONE_API_KEY)",
            },
        }
    
    issues = state.get("issues", [])
    if not issues:
        return {
            "rag_context": [],
            "rag_insights": {"mode": "live", "total_issues": 0, "similar_found": 0},
        }
    
    rag_context = []
    total_similar = 0
    
    try:
        # Get trend analysis
        trends = await query_trend_analysis(days=7)
        
        # For each issue, find similar past incidents
        for issue in issues:
            try:
                # Embed the current issue
                embedding = await embed_issue({
                    "id": issue.id,
                    "title": issue.title,
                    "description": issue.summary,
                    "severity": issue.severity,
                })
                
                # Query for similar incidents
                similar = await query_similar_incidents(
                    embedding=embedding,
                    top_k=3,
                    severity_filter=issue.severity,
                )
                
                if similar:
                    total_similar += len(similar)
                    rag_context.append({
                        "current_issue_id": issue.id,
                        "current_issue_title": issue.title,
                        "similar_incidents": similar,
                    })
            except Exception as e:
                # Log but don't fail on per-issue errors
                print(f"Error retrieving similar incidents for issue {issue.id if hasattr(issue, 'id') else '<unknown>'}: {e}")
                continue
        
        return {
            "rag_context": rag_context,
            "rag_insights": {
                "mode": "live",
                "total_issues": len(issues),
                "similar_found": total_similar,
                "trends": trends,
            },
        }
    
    except Exception as e:
        print(f"RAG agent error: {e}")
        return {
            "rag_context": rag_context,
            "rag_insights": {
                "mode": "live",
                "error": str(e),
                "total_issues": len(issues),
            },
        }
