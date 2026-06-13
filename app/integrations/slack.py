import json
from pathlib import Path

import httpx

from app.config import get_settings


class SlackClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, payload: dict, run_id: str) -> dict:
        if self.settings.slack_configured:
            return self._send_live(payload)
        return self._send_mock(payload, run_id)

    def _send_mock(self, payload: dict, run_id: str) -> dict:
        runs_dir = Path(self.settings.runs_dir) / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        out_path = runs_dir / "slack.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"mode": "mock", "id": f"mock-slack-{run_id}", "path": str(out_path)}

    def _send_live(self, payload: dict) -> dict:
        if self.settings.slack_webhook_url:
            response = httpx.post(self.settings.slack_webhook_url, json=payload, timeout=30.0)
            response.raise_for_status()
            return {"mode": "live", "id": "webhook", "status_code": response.status_code}

        assert self.settings.slack_bot_token and self.settings.slack_channel_id
        headers = {
            "Authorization": f"Bearer {self.settings.slack_bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        body = {
            "channel": self.settings.slack_channel_id,
            "blocks": payload.get("blocks", []),
            "text": payload.get("text", "Ops log analysis update"),
        }
        response = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json=body,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return {"mode": "live", "id": data.get("ts"), "channel": data.get("channel")}


def get_slack_client() -> SlackClient:
    return SlackClient()
