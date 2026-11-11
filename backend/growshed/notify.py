"""Phone notifications through ntfy (https://ntfy.sh or a self-hosted server).

Uses only the standard library. Sending runs in a worker thread so a slow or
unreachable server can never stall sensor ingest or alert evaluation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)
TIMEOUT_S = 10


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    priority: int = 3  # ntfy scale: 1 (min) .. 5 (max, bypasses do-not-disturb if allowed)
    tags: tuple[str, ...] = ()


class Notifier:
    def __init__(self, url: str | None, token: str | None = None) -> None:
        self.url = url.rstrip("/") if url else None
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.url) and "/" in self.url.split("://", 1)[-1]

    def _post(self, note: Notification) -> None:
        base, topic = self.url.rsplit("/", 1)
        payload = {
            "topic": topic,
            "title": note.title,
            "message": note.body,
            "priority": note.priority,
            "tags": list(note.tags),
        }
        request = urllib.request.Request(
            base,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            response.read()

    async def send(self, note: Notification) -> bool:
        """Returns True when delivered to the ntfy server. Never raises."""
        if not self.configured:
            log.info("notification (ntfy not configured): %s | %s", note.title, note.body)
            return True  # nothing to retry
        try:
            await asyncio.to_thread(self._post, note)
            return True
        except Exception as exc:  # noqa: BLE001 - network errors of every kind
            log.warning("ntfy send failed (%s): %s", exc, note.title)
            return False


async def ping(url: str) -> bool:
    """Dead man's switch: tell an outside service the hub is alive. Never raises."""

    def _get() -> None:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310
            response.read()

    try:
        await asyncio.to_thread(_get)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("healthcheck ping failed: %s", exc)
        return False
