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
            attendees: list[str] | None = None,
        ) -> dict:
            """Create a calendar event. `start`/`end` are ISO-8601 (e.g.
            2026-11-20T14:00:00+01:00) or a bare date for all-day. Omit `end` to
            default to +1h (or the whole day when all_day). `reminders_minutes`
            adds alerts that many minutes before. Omit `calendar` for the default.
            `attendees` invites people (iCloud sends the invitations): an email,
            "Name <email>", or a name already on another event's attendee list
            (e.g. "Lea")."""
            return cal.create_event(
                summary, start, end, calendar=calendar, all_day=all_day,
                description=description, location=location, reminders_minutes=reminders_minutes,
                attendees=attendees,
            )

    if enabled("cal_list_events"):
        @mcp.tool()
        def cal_list_events(start: str, end: str, calendar: str | None = None) -> list[dict]:
            """List events between `start` and `end` (ISO-8601) in a calendar
            (or the default one)."""
            return cal.list_events(start, end, calendar=calendar)

    if enabled("cal_update_event"):
        @mcp.tool()
        def cal_update_event(
            uid: str,
            calendar: str | None = None,
            summary: str | None = None,
            start: str | None = None,
            end: str | None = None,
            location: str | None = None,
            description: str | None = None,
            add_attendees: list[str] | None = None,
            remove_attendees: list[str] | None = None,
        ) -> dict:
            """Change an existing event in place (by UID, as listed by
            cal_list_events). Only the fields you pass change; attendees,
            organizer, alarms and everything else stay, so a shared event keeps
            its invitees (they get the update). `start`/`end` are ISO-8601 with
            an offset (e.g. 2027-09-24T23:59:00-10:00); a time stays in the
            event's own time zone. Changing `start` does NOT move `end` - pass
            both to move an event. An empty string clears summary/location/
            description. Recurring events: changes apply to the whole series.
            `add_attendees` invites people (iCloud sends the invitations; you
            become organizer if the event has none): an email, "Name <email>",
            or a name already on another event's attendee list (e.g. "Lea").
            `remove_attendees` drops attendees matching a name or email."""
            return cal.update_event(
                uid, calendar=calendar, summary=summary, start=start, end=end,
                location=location, description=description,
                add_attendees=add_attendees, remove_attendees=remove_attendees,
            )

    if enabled("cal_delete_event"):
        @mcp.tool()
        def cal_delete_event(uid: str, calendar: str | None = None) -> dict:
            """Delete an event by its UID."""
            return cal.delete_event(uid, calendar=calendar)

    # ---- Reminders (read-only) ----------------------------------------
    if enabled("rem_list"):
        @mcp.tool()
        def rem_list(list_name: str | None = None, include_completed: bool = False, limit: int = 200) -> dict:
            """Read-only: list reminders (VTODO items) in a task list. Omit
            `list_name` for the first task list. Note: upgraded iCloud Reminders
            lists are usually not exposed over CalDAV."""
            return cal.list_todos(calendar=list_name, include_completed=include_completed, limit=limit)

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
