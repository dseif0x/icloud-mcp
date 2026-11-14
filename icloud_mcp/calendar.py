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

    @staticmethod
    def _display_name(c: caldav.Calendar) -> str:
        try:
            return c.get_display_name() or ""
        except Exception:
            return c.name or ""

    @staticmethod
    def _supports(c: caldav.Calendar, component: str) -> bool:
        try:
            return component in (c.get_supported_components() or [])
        except Exception:
            return True  # assume usable if the server won't say

    def _find_calendar(self, name: str | None, component: str = "VEVENT") -> caldav.Calendar:
        cals = self._principal_obj().calendars()
        if not cals:
            raise ValueError("no calendars found for this account")
        if name:
            for c in cals:
                if self._display_name(c).casefold() == name.casefold():
                    return c
            raise ValueError(
                f"calendar {name!r} not found; have: " + ", ".join(self._display_name(c) for c in cals)
            )
        # No name: default to the first calendar that holds this component type
        # (skips e.g. the VTODO "Reminders" list when creating an event).
        for c in cals:
            if self._supports(c, component):
                return c
        return cals[0]

    def list_calendars(self) -> list[dict[str, Any]]:
        out = []
        for c in self._principal_obj().calendars():
            try:
                comps = c.get_supported_components() or []
            except Exception:
                comps = []
            out.append({"name": self._display_name(c), "url": str(c.url), "components": comps})
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
                "organizer": _person(vev.get("organizer")),
                "attendees": _attendees(vev),
            })
        out.sort(key=lambda e: e["start"] or "")
        return out

    def list_todos(
        self, *, calendar: str | None = None, include_completed: bool = False, limit: int = 200
    ) -> dict[str, Any]:
        """Read-only: list the VTODO items (reminders) in a task list."""
        cal_obj = self._find_calendar(calendar, component="VTODO")
        items = []
        for t in cal_obj.todos(include_completed=include_completed):
            vt = t.icalendar_component
            items.append({
                "uid": str(vt.get("uid", "")),
                "summary": str(vt.get("summary", "")),
                "status": str(vt.get("status", "")),
                "due": _ical_value(vt.get("due")),
                "completed": _ical_value(vt.get("completed")),
                "priority": str(vt.get("priority", "")),
                "created": _ical_value(vt.get("created")),
                "description": str(vt.get("description", ""))[:500],
            })
            if len(items) >= limit:
                break
        return {"list": self._display_name(cal_obj), "count": len(items), "items": items}

    def update_event(
        self,
        uid: str,
        *,
        calendar: str | None = None,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        location: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Change fields of an existing event in place. Only the fields given
        change; everything else on the VEVENT stays as it is - attendees and
        organizer (shared events keep their invitees), alarms, Apple's X-
        properties, recurrence. The event is written back to the same
        resource (no delete + re-create), with SEQUENCE bumped so invitees'
        calendars take the update."""
        cal_obj = self._find_calendar(calendar)
        res = cal_obj.event_by_uid(uid)
        ical = Calendar.from_ical(res.data)
        vevents = [c for c in ical.walk("VEVENT") if str(c.get("uid", "")) == uid]
        # A recurring event can carry overrides (RECURRENCE-ID); edit the master.
        master = next((v for v in vevents if v.get("recurrence-id") is None), None)
        if master is None:
            raise ValueError(f"event {uid!r} has no master VEVENT")

        changed: list[str] = []
        if summary is not None:
            _set(master, "summary", summary); changed.append("summary")
        if location is not None:
            _set(master, "location", location); changed.append("location")
        if description is not None:
            _set(master, "description", description); changed.append("description")
        for name, value in (("dtstart", start), ("dtend", end)):
            if value is None:
                continue
            old = master.get(name)
            master.pop(name, None)
            master.add(name, _like(old, value))
            changed.append(name)
        if not changed:
            raise ValueError("nothing to change: pass at least one field")
        if "dtend" in changed or "dtstart" in changed:
            s_ = master.get("dtstart").dt
            e_ = master.get("dtend").dt if master.get("dtend") is not None else None
            if e_ is not None and _as_utc(e_) < _as_utc(s_):
                raise ValueError(f"end {e_.isoformat()} is before start {s_.isoformat()}")
            # DURATION and DTEND are exclusive; DTEND wins when we set it.
            if "dtend" in changed:
                master.pop("duration", None)

        seq = int(master.get("sequence", 0)) + 1
        master.pop("sequence", None)
        master.add("sequence", seq)
        now = dt.datetime.now(dt.timezone.utc)
        for name in ("dtstamp", "last-modified"):
            master.pop(name, None)
            master.add(name, now)

        res.data = ical.to_ical()
        res.save()
        return {
            "uid": uid,
            "calendar": self._display_name(cal_obj),
            "changed": changed,
            "summary": str(master.get("summary", "")),
            "start": _ical_value(master.get("dtstart")),
            "end": _ical_value(master.get("dtend")),
            "sequence": seq,
            "attendees": _attendees(master),
        }

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


def _person(prop: Any) -> str:
    if prop is None:
        return ""
    name = prop.params.get("CN", "") if hasattr(prop, "params") else ""
    addr = str(prop).removeprefix("mailto:").removeprefix("MAILTO:")
    return f"{name} <{addr}>" if name else addr


def _attendees(vev: Any) -> list[dict[str, str]]:
    raw = vev.get("attendee")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    out = []
    for a in raw:
        params = getattr(a, "params", {})
        out.append({
            "who": _person(a),
            "status": str(params.get("PARTSTAT", "")),
        })
    return out


def _set(vev: Any, name: str, value: str) -> None:
    vev.pop(name, None)
    if value != "":
        vev.add(name, value)


def _as_utc(v: dt.date | dt.datetime) -> dt.datetime:
    if not isinstance(v, dt.datetime):
        return dt.datetime(v.year, v.month, v.day, tzinfo=dt.timezone.utc)
    if v.tzinfo is None:
        return v.replace(tzinfo=dt.timezone.utc)
    return v.astimezone(dt.timezone.utc)


def _like(old: Any, value: str) -> dt.date | dt.datetime:
    """The new DTSTART/DTEND value, shaped like the old one: an all-day
    (date) value stays a date; a time in a named zone (e.g. TZID=Pacific/
    Tahiti) stays in that zone - converted when the new value carries an
    offset, taken as wall-clock time in that zone when it doesn't. Other
    aware values go in as UTC (a fixed offset like -10:00 has no TZID that
    calendar apps understand)."""
    new = _parse_dt(value)
    old_v = getattr(old, "dt", None)
    if old_v is not None and not isinstance(old_v, dt.datetime):
        return new.date()
    old_tz = old_v.tzinfo if isinstance(old_v, dt.datetime) else None
    named = old_tz is not None and bool(getattr(old_tz, "key", None) or getattr(old_tz, "zone", None))
    if new.tzinfo is None:
        if named:
            return new.replace(tzinfo=old_tz)
        return new
    if named:
        return new.astimezone(old_tz)
    return new.astimezone(dt.timezone.utc)
