"""RAG (Retrieval-Augmented Generation) module for retrieving similar incidents and runbooks."""

from app.rag.embeddings import embed_text, embed_issue
from app.rag.pinecone_client import (
    init_pinecone,
    upsert_incident,
    query_similar_incidents,
    query_trend_analysis,
    get_pinecone_client,
)

__all__ = [
    "embed_text",
    "embed_issue",
    "init_pinecone",
    "upsert_incident",
    "query_similar_incidents",
    "query_trend_analysis",
    "get_pinecone_client",
]
