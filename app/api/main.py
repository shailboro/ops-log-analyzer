import asyncio
import json
import os
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.graph.orchestrator import run_analysis
from app.services.run_store import run_store

app = FastAPI(title="Ops Log Analyzer API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    logs: str = Field(..., min_length=1)
    filename: str | None = None


class AnalyzeResponse(BaseModel):
    run_id: str
    status: str


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_configured": str(settings.llm_configured),
        "slack_mode": "live" if settings.slack_configured else "mock",
        "jira_mode": "live" if settings.jira_configured else "mock",
        "email_mode": "live" if settings.email_configured else "mock",
    }


async def _execute_run(run_id: str, logs: str, filename: str | None) -> None:
    try:
        await run_analysis(run_id, logs, filename)
    except Exception as exc:
        await run_store.fail_run(run_id, str(exc))


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks) -> AnalyzeResponse:
    settings = get_settings()
    if not settings.llm_configured:
        raise HTTPException(status_code=503, detail="LLM not configured. Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY.")

    if len(request.logs.encode("utf-8")) > settings.max_log_bytes:
        raise HTTPException(status_code=413, detail=f"Log exceeds {settings.max_log_bytes} bytes")

    run_id = str(uuid.uuid4())
    await run_store.create_run(run_id, request.logs, request.filename)

    if os.environ.get("VERCEL"):
        await _execute_run(run_id, request.logs, request.filename)
        record = await run_store.get_run(run_id)
        status = record.status if record else "failed"
        return AnalyzeResponse(run_id=run_id, status=status)

    background_tasks.add_task(_execute_run, run_id, request.logs, request.filename)
    return AnalyzeResponse(run_id=run_id, status="running")


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    record = await run_store.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": record.run_id,
        "status": record.status,
        "state": record.state,
        "events": record.events,
        "error": record.error,
    }


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> EventSourceResponse:
    record = await run_store.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        sent = 0
        while True:
            record = await run_store.get_run(run_id)
            if not record:
                break

            while sent < len(record.events):
                yield {"event": "trace", "data": json.dumps(record.events[sent])}
                sent += 1

            if record.status in {"completed", "failed"}:
                payload = {
                    "status": record.status,
                    "error": record.error,
                    "run_id": run_id,
                }
                yield {"event": "done", "data": json.dumps(payload)}
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
