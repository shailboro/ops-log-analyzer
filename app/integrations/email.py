import json
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

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
        assert self.settings.email_smtp_host
        assert self.settings.email_smtp_port
        assert self.settings.email_from
        assert self.settings.email_to

        recipients = [address.strip() for address in self.settings.email_to.split(",") if address.strip()]
        if not recipients:
            raise ValueError("EMAIL_TO must contain at least one recipient")

        message = EmailMessage()
        message["Subject"] = payload.get("subject", "Ops Log Analyzer Notification")
        message["From"] = self.settings.email_from
        message["To"] = ", ".join(recipients)
        body = payload.get("body", "")
        html_body = payload.get("html_body")
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        context = ssl.create_default_context()
        if self.settings.email_use_ssl:
            server = smtplib.SMTP_SSL(
                self.settings.email_smtp_host,
                self.settings.email_smtp_port,
                context=context,
                timeout=30,
            )
        else:
            server = smtplib.SMTP(
                self.settings.email_smtp_host,
                self.settings.email_smtp_port,
                timeout=30,
            )
            if self.settings.email_use_tls:
                server.starttls(context=context)

        try:
            if self.settings.email_smtp_username and self.settings.email_smtp_password:
                server.login(self.settings.email_smtp_username, self.settings.email_smtp_password)
            send_result = server.send_message(message)
        finally:
            server.quit()

        return {
            "mode": "live",
            "id": message["Message-ID"],
            "to": recipients,
            "sent_count": len(send_result) if isinstance(send_result, dict) else 0,
        }


def get_email_client() -> EmailClient:
    return EmailClient()
