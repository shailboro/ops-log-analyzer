"""Embedding functions for RAG using OpenRouter text embeddings."""

import httpx
from typing import Any
import json

from app.config import get_settings


async def embed_text(text: str) -> list[float]:
    """
    Embed text using OpenRouter embeddings API.
    
    Args:
        text: Text to embed
        
    Returns:
        List of floats representing the embedding vector
    """
    settings = get_settings()
    
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is required for embeddings")
    
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": settings.api_base_url,
        "X-Title": "ops-log-analyzer",
    }
    
    payload = {
        "model": "openai/text-embedding-3-small",
        "input": text,
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.openrouter_base_url}/embeddings",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]


async def embed_issue(issue: dict[str, Any]) -> list[float]:
    """
    Embed an issue by combining its title, description, and type.
    
    Args:
        issue: Dict with 'id', 'title', 'description', 'severity'
        
    Returns:
        List of floats representing the embedding vector
    """
    text = f"""
Issue ID: {issue.get('id', 'unknown')}
Title: {issue.get('title', '')}
Description: {issue.get('description', '')}
Severity: {issue.get('severity', 'unknown')}
    """.strip()
    
    return await embed_text(text)


async def embed_remediation(issue_id: str, remediation: str) -> list[float]:
    """
    Embed a remediation/fix text.
    
    Args:
        issue_id: The issue ID this remediation addresses
        remediation: The remediation text
        
    Returns:
        List of floats representing the embedding vector
    """
    text = f"Issue {issue_id}: {remediation}".strip()
    return await embed_text(text)
