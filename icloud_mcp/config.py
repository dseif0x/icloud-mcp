"""Configuration from the environment. No secrets are ever hard-coded; they come
from the Kubernetes Secret mounted as env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    apple_id: str          # Apple ID: CalDAV login (may be a non-iCloud address)
    apple_pw: str
    bearer_token: str
    imap_email: str = ""   # IMAP/SMTP username — iCloud wants the @icloud.com address
    mail_from: str = ""    # From address for sending (defaults to imap_email)
    caldav_url: str = "https://caldav.icloud.com"
    imap_host: str = "imap.mail.me.com"
    imap_port: int = 993
    smtp_host: str = "smtp.mail.me.com"
    smtp_port: int = 587
    # Comma-separated list of tools to disable, e.g. "mail_send".
    disabled_tools: tuple[str, ...] = ()
    host: str = "0.0.0.0"
    port: int = 8080

    @staticmethod
    def from_env() -> "Config":
        def req(name: str) -> str:
            v = os.environ.get(name, "").strip()
            if not v:
                raise SystemExit(f"missing required env var {name}")
            return v

        disabled = tuple(
            t.strip() for t in os.environ.get("ICLOUD_MCP_DISABLED_TOOLS", "").split(",") if t.strip()
        )
        apple_id = req("APPLE_ID")
        imap_email = (os.environ.get("IMAP_EMAIL", "").strip()
                      or os.environ.get("MAIL_FROM", "").strip() or apple_id)
        return Config(
            apple_id=apple_id,
            apple_pw=req("APPLE_APP_PW"),
            bearer_token=req("MCP_BEARER_TOKEN"),
            imap_email=imap_email,
            mail_from=os.environ.get("MAIL_FROM", "").strip() or imap_email,
            caldav_url=os.environ.get("CALDAV_URL", "https://caldav.icloud.com"),
            imap_host=os.environ.get("IMAP_HOST", "imap.mail.me.com"),
            imap_port=int(os.environ.get("IMAP_PORT", "993")),
            smtp_host=os.environ.get("SMTP_HOST", "smtp.mail.me.com"),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            disabled_tools=disabled,
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
        )
