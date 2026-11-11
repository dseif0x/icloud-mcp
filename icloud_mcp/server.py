"""iCloud MCP server: Calendar (CalDAV) + Mail (IMAP/SMTP) over Streamable HTTP,
guarded by a static bearer token. Reminders are intentionally out of scope —
modern iCloud Reminders aren't reachable over CalDAV."""
from __future__ import annotations

import logging

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .calendar import CalendarClient
from .config import Config
from .mail import MailClient

log = logging.getLogger("icloud-mcp")


class BearerAuth(BaseHTTPMiddleware):
    """Rejects any request without `Authorization: Bearer <token>`, except the
    unauthenticated health check."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self._expected = f"Bearer {token}"

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth != self._expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build(cfg: Config) -> FastMCP:
    mcp = FastMCP("icloud", host=cfg.host, port=cfg.port)
    cal = CalendarClient(cfg)
    mail = MailClient(cfg)
    enabled = lambda name: name not in cfg.disabled_tools  # noqa: E731

    # ---- Calendar -------------------------------------------------------
    if enabled("cal_list_calendars"):
        @mcp.tool()
        def cal_list_calendars() -> list[dict]:
            """List the account's calendars (name + URL)."""
            return cal.list_calendars()

    if enabled("cal_create_event"):
        @mcp.tool()
        def cal_create_event(
            summary: str,
            start: str,
            end: str | None = None,
            calendar: str | None = None,
            all_day: bool = False,
            description: str = "",
            location: str = "",
            reminders_minutes: list[int] | None = None,
        ) -> dict:
            """Create a calendar event. `start`/`end` are ISO-8601 (e.g.
            2026-11-20T14:00:00+01:00) or a bare date for all-day. Omit `end` to
            default to +1h (or the whole day when all_day). `reminders_minutes`
            adds alerts that many minutes before. Omit `calendar` for the default."""
            return cal.create_event(
                summary, start, end, calendar=calendar, all_day=all_day,
                description=description, location=location, reminders_minutes=reminders_minutes,
            )

    if enabled("cal_list_events"):
        @mcp.tool()
        def cal_list_events(start: str, end: str, calendar: str | None = None) -> list[dict]:
            """List events between `start` and `end` (ISO-8601) in a calendar
            (or the default one)."""
            return cal.list_events(start, end, calendar=calendar)

    if enabled("cal_delete_event"):
        @mcp.tool()
        def cal_delete_event(uid: str, calendar: str | None = None) -> dict:
            """Delete an event by its UID."""
            return cal.delete_event(uid, calendar=calendar)

    # ---- Mail -----------------------------------------------------------
    if enabled("mail_list_folders"):
        @mcp.tool()
        def mail_list_folders() -> list[str]:
            """List IMAP mailbox folders."""
            return mail.list_folders()

    if enabled("mail_search"):
        @mcp.tool()
        def mail_search(
            folder: str = "INBOX",
            unseen: bool = False,
            since_days: int | None = None,
            from_: str | None = None,
            subject: str | None = None,
            text: str | None = None,
            limit: int = 20,
        ) -> list[dict]:
            """Search a mail folder. Returns summaries (uid, subject, from, date,
            flags, snippet). Filters combine with AND."""
            return mail.search(
                folder=folder, unseen=unseen, since_days=since_days,
                from_=from_, subject=subject, text=text, limit=limit,
            )

    if enabled("mail_get"):
        @mcp.tool()
        def mail_get(uid: str, folder: str = "INBOX", mark_seen: bool = False) -> dict:
            """Fetch a full message by UID: headers, body text/html, attachment list."""
            return mail.get(uid, folder=folder, mark_seen=mark_seen)

    if enabled("mail_send"):
        @mcp.tool()
        def mail_send(to: list[str], subject: str, body: str, cc: list[str] | None = None) -> dict:
            """Send a plain-text email from the account."""
            return mail.send(to, subject, body, cc=cc)

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.from_env()
    mcp = build(cfg)

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuth, token=cfg.bearer_token)

    async def healthz(_req: Request):
        return PlainTextResponse("ok")

    app.add_route("/healthz", healthz, methods=["GET"])

    log.info("icloud-mcp listening on %s:%s (mcp at /mcp)", cfg.host, cfg.port)
    log.info("tools disabled: %s", ", ".join(cfg.disabled_tools) or "none")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
