import json
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings


class EmailClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, payload: dict[str, Any], run_id: str) -> dict[str, Any]:
        if self.settings.email_configured:
            return self._send_live(payload)
        return self._send_mock(payload, run_id)

    def _send_mock(self, payload: dict[str, Any], run_id: str) -> dict[str, Any]:
        runs_dir = Path(self.settings.runs_dir) / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        out_path = runs_dir / "email.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "mode": "mock",
            "id": f"mock-email-{run_id}",
            "path": str(out_path),
        }

    def _send_live(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.settings.resend_api_key
        assert self.settings.email_from
        assert self.settings.email_to

        recipients = [address.strip() for address in self.settings.email_to.split(",") if address.strip()]
        if not recipients:
            raise ValueError("EMAIL_TO must contain at least one recipient")

        request_payload: dict[str, Any] = {
            "from": self.settings.email_from,
            "to": recipients,
            "subject": payload.get("subject", "Ops Log Analyzer Notification"),
            "text": payload.get("body", ""),
        }
        html_body = payload.get("html_body")
        if html_body:
            request_payload["html"] = html_body

        headers = {
            "Authorization": f"Bearer {self.settings.resend_api_key}",
            "Content-Type": "application/json",
        }

        response = httpx.post(
            "https://api.resend.com/emails",
            json=request_payload,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        return {
            "mode": "live",
            "id": data.get("id"),
            "to": recipients,
            "response": data,
        }


def get_email_client() -> EmailClient:
    return EmailClient()
