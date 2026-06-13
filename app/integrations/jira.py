import json
from pathlib import Path

import httpx

from app.config import get_settings


class JiraClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, payload: dict, run_id: str) -> dict:
        if self.settings.jira_configured:
            return self._send_live(payload)
        return self._send_mock(payload, run_id)

    def _send_mock(self, payload: dict, run_id: str) -> dict:
        runs_dir = Path(self.settings.runs_dir) / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        out_path = runs_dir / "jira.json"
        existing: list[dict] = []
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        existing.append(payload)
        out_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        return {
            "mode": "mock",
            "id": payload.get("key", f"mock-jira-{run_id}-{len(existing)}"),
            "path": str(out_path),
        }

    def _send_live(self, payload: dict) -> dict:
        assert self.settings.jira_base_url
        url = f"{self.settings.jira_base_url.rstrip('/')}/rest/api/3/issue"
        auth = (self.settings.jira_email or "", self.settings.jira_api_token or "")
        body = {
            "fields": {
                "project": {"key": self.settings.jira_project_key},
                "summary": payload["summary"],
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": payload["description"]}],
                        }
                    ],
                },
                "issuetype": {"name": payload.get("issuetype", "Task")},
                "priority": {"name": payload.get("priority", "High")},
            }
        }
        response = httpx.post(url, json=body, auth=auth, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        issue_key = data.get("key")
        issue_url = f"{self.settings.jira_base_url.rstrip('/')}/browse/{issue_key}"
        return {"mode": "live", "id": issue_key, "url": issue_url}


def get_jira_client() -> JiraClient:
    return JiraClient()
