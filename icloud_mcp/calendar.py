"""iCloud calendar access over CalDAV."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import caldav
from icalendar import Alarm, Calendar, Event

from .config import Config


def _parse_dt(value: str) -> dt.datetime:
    """Parses an ISO-8601 datetime. A bare date (YYYY-MM-DD) is treated as the
    start of that day. Naive datetimes are assumed to be in the server's TZ."""
    value = value.strip()
    if len(value) == 10 and value[4] == "-":
        d = dt.date.fromisoformat(value)
        return dt.datetime(d.year, d.month, d.day)
    # Allow a trailing 'Z' for UTC.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return dt.datetime.fromisoformat(value)


class CalendarClient:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._principal: caldav.Principal | None = None

    def _principal_obj(self) -> caldav.Principal:
        if self._principal is None:
            client = caldav.DAVClient(
                url=self._cfg.caldav_url,
                username=self._cfg.apple_id,
                password=self._cfg.apple_pw,
            )
            self._principal = client.principal()
        return self._principal

    def _find_calendar(self, name: str | None) -> caldav.Calendar:
        cals = self._principal_obj().calendars()
        if not cals:
            raise ValueError("no calendars found for this account")
        if not name:
            return cals[0]
        for c in cals:
            if (c.name or "").casefold() == name.casefold():
                return c
        raise ValueError(f"calendar {name!r} not found; have: " + ", ".join(c.name or "?" for c in cals))

    def list_calendars(self) -> list[dict[str, Any]]:
        out = []
        for c in self._principal_obj().calendars():
            out.append({"name": c.name, "url": str(c.url)})
        return out

    def create_event(
        self,
        summary: str,
        start: str,
        end: str | None = None,
        *,
        calendar: str | None = None,
        all_day: bool = False,
        description: str = "",
        location: str = "",
        reminders_minutes: list[int] | None = None,
    ) -> dict[str, Any]:
        cal_obj = self._find_calendar(calendar)
        start_dt = _parse_dt(start)
        if end:
            end_dt = _parse_dt(end)
        elif all_day:
            end_dt = start_dt + dt.timedelta(days=1)
        else:
            end_dt = start_dt + dt.timedelta(hours=1)

        ev = Event()
        uid = str(uuid.uuid4())
        ev["uid"] = uid
        ev.add("summary", summary)
        if all_day:
            ev.add("dtstart", start_dt.date())
            ev.add("dtend", end_dt.date())
        else:
            ev.add("dtstart", start_dt)
            ev.add("dtend", end_dt)
        ev.add("dtstamp", dt.datetime.now(dt.timezone.utc))
        if description:
            ev.add("description", description)
        if location:
            ev.add("location", location)
        for minutes in reminders_minutes or []:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", summary)
            alarm.add("trigger", dt.timedelta(minutes=-abs(minutes)))
            ev.add_component(alarm)

        cal = Calendar()
        cal.add("prodid", "-//icloud-mcp//EN")
        cal.add("version", "2.0")
        cal.add_component(ev)
        cal_obj.save_event(cal.to_ical())
        return {"uid": uid, "calendar": cal_obj.name, "summary": summary,
                "start": start_dt.isoformat(), "end": end_dt.isoformat()}

    def list_events(self, start: str, end: str, *, calendar: str | None = None) -> list[dict[str, Any]]:
        cal_obj = self._find_calendar(calendar)
        results = cal_obj.search(
            start=_parse_dt(start), end=_parse_dt(end), event=True, expand=True
        )
        out = []
        for r in results:
            vev = r.icalendar_component
            out.append({
                "uid": str(vev.get("uid", "")),
                "summary": str(vev.get("summary", "")),
                "start": _ical_value(vev.get("dtstart")),
                "end": _ical_value(vev.get("dtend")),
                "location": str(vev.get("location", "")),
            })
        out.sort(key=lambda e: e["start"] or "")
        return out

    def delete_event(self, uid: str, *, calendar: str | None = None) -> dict[str, Any]:
        cal_obj = self._find_calendar(calendar)
        ev = cal_obj.event_by_uid(uid)
        ev.delete()
        return {"deleted": uid}


def _ical_value(prop: Any) -> str:
    if prop is None:
        return ""
    v = getattr(prop, "dt", prop)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return str(v)
