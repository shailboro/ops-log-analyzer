"""Pinecone client for RAG vector storage and retrieval."""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from pinecone import Pinecone

from app.config import get_settings


@lru_cache(maxsize=1)
def get_pinecone_client() -> Pinecone | None:
    """
    Get or initialize Pinecone client.
    
    Returns:
        Pinecone client instance or None if not configured
    """
    settings = get_settings()
    
    if not settings.pinecone_api_key:
        return None
    
    return Pinecone(api_key=settings.pinecone_api_key)


async def init_pinecone() -> bool:
    """
    Initialize Pinecone index if it doesn't exist.
    
    Returns:
        True if successful, False if Pinecone not configured
    """
    settings = get_settings()
    
    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return False
    
    pc = get_pinecone_client()
    if not pc:
        return False
    
    # Check if index exists, create if not
    indexes = pc.list_indexes()
    index_names = [idx.name for idx in indexes.indexes]
    
    if settings.pinecone_index_name not in index_names:
        pc.create_index(
            name=settings.pinecone_index_name,
            dimension=1536,  # OpenAI text-embedding-3-small dimension
            metric="cosine",
            spec={
                "serverless": {
                    "cloud": "aws",
                    "region": settings.pinecone_environment or "us-east-1",
                }
            },
        )
    
    return True


async def upsert_incident(
    run_id: str,
    issue_id: str,
    embedding: list[float],
    issue_data: dict[str, Any],
    remediation: str | None = None,
) -> bool:
    """
    Store an incident and optionally its remediation in Pinecone.
    
    Args:
        run_id: Analysis run ID
        issue_id: Issue identifier
        embedding: Vector embedding of the issue
        issue_data: Dict with 'title', 'description', 'severity'
        remediation: Optional remediation/fix text
        
    Returns:
        True if successful, False if Pinecone not configured
    """
    settings = get_settings()
    
    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return False
    
    pc = get_pinecone_client()
    if not pc:
        return False
    
    index = pc.Index(settings.pinecone_index_name)
    
    # Store issue embedding
    metadata = {
        "run_id": run_id,
        "issue_id": issue_id,
        "type": "issue",
        "title": issue_data.get("title", ""),
        "description": issue_data.get("description", ""),
        "severity": issue_data.get("severity", "unknown"),
        "timestamp": datetime.now().isoformat(),
    }
    
    vector_id = f"{run_id}_{issue_id}_issue"
    index.upsert([(vector_id, embedding, metadata)])
    
    # Store remediation if provided
    if remediation:
        metadata["type"] = "remediation"
        metadata["remediation"] = remediation
        
        vector_id_rem = f"{run_id}_{issue_id}_remediation"
        index.upsert([(vector_id_rem, embedding, metadata)])
    
    return True


async def query_similar_incidents(
    embedding: list[float],
    top_k: int = 5,
    severity_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    Query Pinecone for similar past incidents.
    
    Args:
        embedding: Vector embedding to search with
        top_k: Number of similar incidents to return
        severity_filter: Optional severity to filter by
        
    Returns:
        List of similar incidents with metadata
    """
    settings = get_settings()
    
    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return []
    
    pc = get_pinecone_client()
    if not pc:
        return []
    
    index = pc.Index(settings.pinecone_index_name)
    
    # Build filter for issue type
    filter_dict = {"type": {"$eq": "issue"}}
    
    if severity_filter:
        filter_dict["severity"] = {"$eq": severity_filter}
    
    results = index.query(
        vector=embedding,
        top_k=top_k,
        include_metadata=True,
        filter=filter_dict,
    )
    
    incidents = []
    for match in results.matches:
        incidents.append(
            {
                "id": match.metadata.get("issue_id"),
                "title": match.metadata.get("title"),
                "description": match.metadata.get("description"),
                "severity": match.metadata.get("severity"),
                "score": match.score,
            }
        )
    
    return incidents


async def query_trend_analysis(days: int = 7) -> dict[str, Any]:
    """
    Query Pinecone for incident trends over time.
    
    Args:
        days: Number of days to look back (default 7)
        
    Returns:
        Dict with trend analysis including counts by severity
    """
    settings = get_settings()
    
    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return {}
    
    pc = get_pinecone_client()
    if not pc:
        return {}
    
    index = pc.Index(settings.pinecone_index_name)
    
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    # Query all issues in the time window
    filter_dict = {
        "type": {"$eq": "issue"},
        "timestamp": {"$gte": cutoff_date},
    }
    
    results = index.query(
        vector=[0.0] * 1536,  # Dummy vector, we're filtering only
        top_k=1000,
        include_metadata=True,
        filter=filter_dict,
    )
    
    # Aggregate by severity
    severity_counts = {}
    issue_titles = []
    
    for match in results.matches:
        severity = match.metadata.get("severity", "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        title = match.metadata.get("title", "")
        if title and title not in issue_titles:
            issue_titles.append(title)
    
    return {
        "period_days": days,
        "total_issues": len(results.matches),
        "by_severity": severity_counts,
        "recent_titles": issue_titles[-5:],  # Last 5 unique titles
    }
