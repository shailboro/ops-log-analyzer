"""Pinecone client for RAG vector storage and retrieval."""

import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from pinecone import Pinecone

from app.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 1536


def _normalize_index_host(host: str) -> str:
    host = host.strip()
    if host.startswith("https://"):
        return host[len("https://") :]
    if host.startswith("http://"):
        return host[len("http://") :]
    return host


def _index_region(settings) -> str:
    """Resolve serverless region from PINECONE_ENVIRONMENT."""
    environment = (settings.pinecone_environment or "us-east-1").strip()
    if environment.startswith("https://") or environment.startswith("http://"):
        return "us-east-1"
    if "pinecone.io" in environment:
        return "us-east-1"
    if environment.startswith("controller."):
        return "us-east-1"
    return environment


@lru_cache(maxsize=1)
def get_pinecone_client() -> Pinecone | None:
    """
    Return the Pinecone control-plane client.

    PINECONE_HOST is the data-plane index host and must not be passed here.
    """
    settings = get_settings()
    if not settings.pinecone_api_key:
        return None

    client_kwargs: dict[str, Any] = {"api_key": settings.pinecone_api_key}
    controller_host = os.environ.get("PINECONE_CONTROLLER_HOST")
    if controller_host:
        client_kwargs["host"] = controller_host

    return Pinecone(**client_kwargs)


def _get_index():
    settings = get_settings()
    pc = get_pinecone_client()
    if not pc:
        return None

    if settings.pinecone_host:
        return pc.Index(
            settings.pinecone_index_name,
            host=_normalize_index_host(settings.pinecone_host),
        )
    return pc.Index(settings.pinecone_index_name)


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

    indexes = pc.list_indexes()
    index_names = [idx.name for idx in indexes.indexes]

    if settings.pinecone_index_name not in index_names:
        pc.create_index(
            name=settings.pinecone_index_name,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec={
                "serverless": {
                    "cloud": "aws",
                    "region": _index_region(settings),
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

    Returns:
        True if successful, False if Pinecone not configured
    """
    settings = get_settings()

    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return False

    index = _get_index()
    if not index:
        return False

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
    response = index.upsert(
        vectors=[{"id": vector_id, "values": embedding, "metadata": metadata}]
    )
    logger.info(
        "Upserted issue vector %s to index %s (upserted=%s)",
        vector_id,
        settings.pinecone_index_name,
        response.upserted_count,
    )

    if remediation:
        remediation_metadata = {
            **metadata,
            "type": "remediation",
            "remediation": remediation,
        }
        vector_id_rem = f"{run_id}_{issue_id}_remediation"
        index.upsert(
            vectors=[
                {
                    "id": vector_id_rem,
                    "values": embedding,
                    "metadata": remediation_metadata,
                }
            ]
        )

    return True


async def query_similar_incidents(
    embedding: list[float],
    top_k: int = 5,
    severity_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query Pinecone for similar past incidents."""
    settings = get_settings()

    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return []

    index = _get_index()
    if not index:
        return []

    filter_dict: dict[str, Any] = {"type": {"$eq": "issue"}}
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
        if match.metadata is None:
            continue
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
    """Query Pinecone for incident trends over time."""
    settings = get_settings()

    if not settings.pinecone_api_key or not settings.pinecone_index_name:
        return {}

    index = _get_index()
    if not index:
        return {}

    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    filter_dict = {
        "type": {"$eq": "issue"},
        "timestamp": {"$gte": cutoff_date},
    }

    results = index.query(
        vector=[0.0] * EMBEDDING_DIMENSION,
        top_k=1000,
        include_metadata=True,
        filter=filter_dict,
    )

    severity_counts: dict[str, int] = {}
    issue_titles: list[str] = []

    for match in results.matches:
        if match.metadata is None:
            continue
        severity = match.metadata.get("severity", "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        title = match.metadata.get("title", "")
        if title and title not in issue_titles:
            issue_titles.append(title)

    return {
        "period_days": days,
        "total_issues": len(results.matches),
        "by_severity": severity_counts,
        "recent_titles": issue_titles[-5:],
    }
