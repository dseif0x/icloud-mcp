"""iCloud mail access over IMAP (read) and SMTP (send)."""
from __future__ import annotations

import datetime as dt
import smtplib
from email.message import EmailMessage
from typing import Any

from imap_tools import AND, MailBox

from .config import Config


class MailClient:
    def __init__(self, cfg: Config):
        self._cfg = cfg

    def _box(self) -> MailBox:
        return MailBox(self._cfg.imap_host, port=self._cfg.imap_port).login(
            self._cfg.imap_email, self._cfg.apple_pw
        )

    def list_folders(self) -> list[str]:
        with self._box() as mb:
            return [f.name for f in mb.folder.list()]

    def search(
        self,
        *,
        folder: str = "INBOX",
        unseen: bool = False,
        since_days: int | None = None,
        from_: str | None = None,
        subject: str | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        crit: dict[str, Any] = {}
        if unseen:
            crit["seen"] = False
        if since_days is not None:
            crit["date_gte"] = (dt.date.today() - dt.timedelta(days=since_days))
        if from_:
            crit["from_"] = from_
        if subject:
            crit["subject"] = subject
        if text:
            crit["text"] = text
        query = AND(**crit) if crit else AND(all=True)

        out = []
        with self._box() as mb:
            mb.folder.set(folder)
            for msg in mb.fetch(query, limit=limit, reverse=True, mark_seen=False, headers_only=False, bulk=True):
                out.append({
                    "uid": msg.uid,
                    "subject": msg.subject,
                    "from": msg.from_,
                    "to": list(msg.to),
                    "date": msg.date.isoformat() if msg.date else "",
                    "flags": list(msg.flags),
                    "snippet": (msg.text or msg.html or "")[:280].strip(),
                    "has_attachments": bool(msg.attachments),
                })
        return out

    def get(self, uid: str, *, folder: str = "INBOX", mark_seen: bool = False) -> dict[str, Any]:
        with self._box() as mb:
            mb.folder.set(folder)
            for msg in mb.fetch(AND(uid=uid), mark_seen=mark_seen, bulk=False):
                return {
                    "uid": msg.uid,
                    "subject": msg.subject,
                    "from": msg.from_,
                    "to": list(msg.to),
                    "cc": list(msg.cc),
                    "date": msg.date.isoformat() if msg.date else "",
                    "text": msg.text or "",
                    "html": msg.html or "",
                    "attachments": [{"name": a.filename, "size": a.size, "type": a.content_type}
                                    for a in msg.attachments],
                }
        raise ValueError(f"message uid {uid} not found in {folder}")

    def allowed_from(self) -> list[str]:
        """The From addresses send() accepts: MAIL_FROM plus MAIL_FROM_ALIASES."""
        seen: list[str] = []
        for a in (self._cfg.mail_from, *self._cfg.mail_from_aliases):
            if a and a.lower() not in [s.lower() for s in seen]:
                seen.append(a)
        return seen

    def send(self, to: list[str], subject: str, body: str, *, cc: list[str] | None = None,
             from_address: str | None = None,
             attachments: list[tuple[str, str, bytes]] | None = None) -> dict[str, Any]:
        """Sends a plain-text mail. from_address must be MAIL_FROM or one of
        MAIL_FROM_ALIASES; attachments are (filename, content type, data)."""
        sender = self._cfg.mail_from
        if from_address:
            allowed = {a.lower(): a for a in self.allowed_from()}
            if from_address.strip().lower() not in allowed:
                raise ValueError(f"from_address must be one of: {', '.join(self.allowed_from())}")
            sender = from_address.strip()
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)
        for filename, ctype, data in attachments or []:
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=maintype or "application", subtype=subtype or "octet-stream",
                               filename=filename)

        recipients = list(to) + list(cc or [])
        with smtplib.SMTP(self._cfg.smtp_host, self._cfg.smtp_port) as s:
            s.starttls()
            s.login(self._cfg.imap_email, self._cfg.apple_pw)
            s.send_message(msg, to_addrs=recipients)
        return {"sent": True, "from": sender, "to": recipients, "subject": subject,
                "attachments": [f for f, _, _ in attachments or []]}
