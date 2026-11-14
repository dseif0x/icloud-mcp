# Offline test of CalendarClient.update_event against a fake CalDAV resource:
#   python tests/test_update_event.py   (needs the requirements installed)
import sys, datetime as dt
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from icalendar import Calendar
from icloud_mcp.calendar import CalendarClient

SHARED = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//iPhone OS 18//EN
BEGIN:VTIMEZONE
TZID:Pacific/Tahiti
BEGIN:STANDARD
DTSTART:19120101T000000
TZOFFSETFROM:-0958
TZOFFSETTO:-1000
TZNAME:GMT-10
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:9c060852-19e9-442b-874d-88780269b667
DTSTART;TZID=Pacific/Tahiti:20270924T235900
DTEND;TZID=Pacific/Tahiti:20270925T082000
SUMMARY:Flug PPT - LAX (TN 102)
LOCATION:Faa'a International Airport\\, Papeete (PPT)
ORGANIZER;CN=Daniel Seifert:mailto:dan@seifert.id
ATTENDEE;CN=Daniel Seifert;PARTSTAT=ACCEPTED;ROLE=CHAIR:mailto:dan@seifert.id
ATTENDEE;CN=Lea Machain;PARTSTAT=ACCEPTED;CUTYPE=INDIVIDUAL:mailto:lea@example.com
SEQUENCE:3
X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-PT2H
DESCRIPTION:Reminder
END:VALARM
DTSTAMP:20261101T100000Z
END:VEVENT
END:VCALENDAR
"""
ALLDAY = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:x
BEGIN:VEVENT
UID:allday-1
DTSTART;VALUE=DATE:20270827
DTEND;VALUE=DATE:20270927
SUMMARY:Urlaub
DTSTAMP:20261101T100000Z
END:VEVENT
END:VCALENDAR
"""

class FakeRes:
    def __init__(self, data): self.data = data; self.saved = 0
    def save(self): self.saved += 1

class FakeCal:
    name = "Privat"
    def __init__(self, res): self.res = res
    def event_by_uid(self, uid): return self.res

def client_for(res):
    c = CalendarClient.__new__(CalendarClient)
    c._find_calendar = lambda name, component="VEVENT": FakeCal(res)
    c._display_name = lambda cal: "Privat"
    return c

# 1) shared event: change only the end, given as LA time with offset
res = FakeRes(SHARED)
out = client_for(res).update_event("9c060852-19e9-442b-874d-88780269b667", end="2027-09-25T10:50:00-07:00")
print("result:", out)
assert res.saved == 1
ev = Calendar.from_ical(res.data).walk("VEVENT")[0]
text = res.data.decode()
print(text)
assert ev["dtend"].dt.isoformat() == "2027-09-25T07:50:00-10:00", ev["dtend"].dt
assert "DTEND;TZID=Pacific/Tahiti:20270925T075000" in text
assert "DTSTART;TZID=Pacific/Tahiti:20270924T235900" in text        # untouched
assert text.count("ATTENDEE") == 2 and "Lea Machain" in text and "PARTSTAT=ACCEPTED" in text
assert "ORGANIZER;CN=\"Daniel Seifert\"" in text
assert "BEGIN:VALARM" in text and "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR" in text
assert "BEGIN:VTIMEZONE" in text
assert int(ev["sequence"]) == 4
assert "LOCATION:Faa'a International Airport\\, Papeete (PPT)" in text
assert out["attendees"][1]["who"] == "Lea Machain <lea@example.com>"

# 2) end before start is refused, nothing saved
res2 = FakeRes(SHARED)
try:
    client_for(res2).update_event("9c060852-19e9-442b-874d-88780269b667", end="2027-09-24T20:00:00-10:00")
    raise SystemExit("expected ValueError")
except ValueError as e:
    print("refused:", e); assert res2.saved == 0

# 3) naive time = wall clock in the event's zone
res3 = FakeRes(SHARED)
client_for(res3).update_event("9c060852-19e9-442b-874d-88780269b667", start="2027-09-24T23:30:00")
assert "DTSTART;TZID=Pacific/Tahiti:20270924T233000" in res3.data.decode()

# 4) all-day stays all-day; summary change
res4 = FakeRes(ALLDAY)
client_for(res4).update_event("allday-1", end="2027-09-28", summary="Urlaub Tahiti")
t4 = res4.data.decode(); print(t4)
assert "DTEND;VALUE=DATE:20270928" in t4 and "SUMMARY:Urlaub Tahiti" in t4

# 5) nothing to change
try:
    client_for(FakeRes(ALLDAY)).update_event("allday-1"); raise SystemExit("expected ValueError")
except ValueError: pass
print("ALL OK")
