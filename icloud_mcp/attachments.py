"""In-memory store for mail attachments uploaded over HTTP.

Agents can't put a binary file into a tool call, so they upload it first:

    curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/pdf" \\
         --data-binary @invoice.pdf "http://icloud-mcp.mcp:8080/attachments?filename=invoice.pdf"
    -> {"id": "...", "filename": "invoice.pdf", "size": 82134, "expires_in": 3600}

and pass the id to mail_send(attachment_ids=[...]). Nothing touches disk (the
container's root filesystem is read-only); uploads expire after a TTL and the
store has a total size cap. One replica, so in-process memory is enough.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes
    expires: float


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str) -> str:
    """A plain file name: no path, no control or odd characters."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _SAFE_NAME.sub("_", name).strip(" .")
    return (name or "attachment")[:120]


class AttachmentStore:
    def __init__(self, ttl_seconds: int, max_bytes: int):
        self._ttl = ttl_seconds
        self._max = max_bytes
        self._items: dict[str, Attachment] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.monotonic()
        for k in [k for k, v in self._items.items() if v.expires <= now]:
            del self._items[k]

    def put(self, filename: str, content_type: str, data: bytes) -> dict:
        if not data:
            raise ValueError("empty upload")
        with self._lock:
            self._expire()
            used = sum(len(v.data) for v in self._items.values())
            if used + len(data) > self._max:
                raise ValueError(f"attachment store full ({self._max} bytes); retry after older uploads expire")
            aid = secrets.token_urlsafe(16)
            self._items[aid] = Attachment(safe_filename(filename), content_type or "application/octet-stream",
                                          data, time.monotonic() + self._ttl)
        return {"id": aid, "filename": self._items[aid].filename, "size": len(data), "expires_in": self._ttl}

    def get(self, aid: str) -> Attachment:
        with self._lock:
            self._expire()
            a = self._items.get(aid)
        if a is None:
            raise KeyError(f"unknown or expired attachment id: {aid}")
        return a

    def pop(self, aid: str) -> None:
        with self._lock:
            self._items.pop(aid, None)
