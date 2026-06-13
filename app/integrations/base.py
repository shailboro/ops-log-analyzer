from typing import Protocol


class Notifier(Protocol):
    def send(self, payload: dict, run_id: str) -> dict:
        """Send payload and return metadata like mode, id, url."""
