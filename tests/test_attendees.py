# Offline test of attendee handling (create/update): python tests/test_attendees.py
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from icalendar import Calendar
from icloud_mcp.calendar import CalendarClient

DAN = "/aNTkzNDI3MzA3NTkzNDI3M-qo9kjZSK2RtPAF46MzkXHB9ORoqEK0j2R9LYsI7A7c/principal/"
LEA = "/aODM3MDI0Mzk0NTgzNzAyNLg60e-9ItgwTWFvsOyIOT50eOVPONDEZC5jCgbj6_Kr/principal/"
SHARED = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:x
BEGIN:VEVENT
UID:flight
DTSTART:20270827T054500Z
DTEND:20270827T071000Z
SUMMARY:Flug
ORGANIZER;CN=Daniel Seifert;EMAIL=dan@seifert.id:{DAN}
ATTENDEE;CN=Daniel Seifert;PARTSTAT=ACCEPTED;ROLE=CHAIR:{DAN}
ATTENDEE;CN=Lea Machain;CUTYPE=INDIVIDUAL;EMAIL=lea@example.com;PARTSTAT=ACCEPTED:{LEA}
DTSTAMP:20261101T100000Z
END:VEVENT
END:VCALENDAR
""".encode()
PLAIN = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//icloud-mcp//EN
BEGIN:VEVENT
UID:elfi
DTSTART:20270116T110000Z
DTEND:20270116T120000Z
SUMMARY:Elfi Holzinger
DTSTAMP:20261114T100000Z
END:VEVENT
END:VCALENDAR
"""

class FakeRes:
    def __init__(self, data): self.data = data; self.saved = 0
    def save(self): self.saved += 1
    @property
    def icalendar_instance(self): return Calendar.from_ical(self.data)

class FakeCal:
    name = "Privat"
    def __init__(self, target, others): self.target, self.others = target, others
    def event_by_uid(self, uid): return self.target
    def search(self, **kw): return self.others
    def save_event(self, data): self.created = data

class FakePrincipal:
    url = None
    def calendar_user_address_set(self): return ["mailto:dan@seifert.id", DAN, "urn:uuid:x"]
    def get_display_name(self): return "Daniel Seifert"

def client(cal):
    c = CalendarClient.__new__(CalendarClient)
    c._find_calendar = lambda name, component="VEVENT": cal
    c._display_name = lambda x: "Privat"
    c._principal_obj = lambda: FakePrincipal()
    return c

# 1) invite "Lea" to an event without organizer: resolved from the shared flight
res = FakeRes(PLAIN)
cal = FakeCal(res, [FakeRes(SHARED)])
out = client(cal).update_event("elfi", calendar="Privat", add_attendees=["Lea"])
print(out)
t = res.data.decode(); print(t)
ev = Calendar.from_ical(res.data).walk("VEVENT")[0]
assert str(ev["organizer"]) == DAN
atts = ev["attendee"]; assert isinstance(atts, list) and len(atts) == 2
lea = [a for a in atts if str(a) == LEA][0]
assert lea.params["PARTSTAT"] == "NEEDS-ACTION" and lea.params["RSVP"] == "TRUE"
assert lea.params["EMAIL"] == "lea@example.com" and lea.params["CN"] == "Lea Machain"
me = [a for a in atts if str(a) == DAN][0]; assert me.params["ROLE"] == "CHAIR"
assert int(ev["sequence"]) == 1 and out["changed"] == ["attendees+Lea Machain <lea@example.com>"]

# 2) again: no duplicate, nothing to change
res2 = FakeRes(res.data)
try:
    client(FakeCal(res2, [FakeRes(SHARED)])).update_event("elfi", add_attendees=["lea@example.com"])
    raise SystemExit("expected ValueError (nothing to change)")
except ValueError as e:
    print("dup skipped:", e)

# 3) email and "Name <email>" forms, then remove one
res3 = FakeRes(PLAIN)
client(FakeCal(res3, [])).update_event("elfi", add_attendees=["max@example.org", "Eva Example <eva@example.org>"])
ev3 = Calendar.from_ical(res3.data).walk("VEVENT")[0]
assert {str(a) for a in ev3["attendee"]} == {DAN, "mailto:max@example.org", "mailto:eva@example.org"}
res3b = FakeRes(res3.data)
out3 = client(FakeCal(res3b, [])).update_event("elfi", remove_attendees=["max"])
ev3b = Calendar.from_ical(res3b.data).walk("VEVENT")[0]
assert {str(a) for a in ev3b["attendee"]} == {DAN, "mailto:eva@example.org"}, out3

# 4) unknown / ambiguous names are refused
for name, others in (("Nobody", [FakeRes(SHARED)]), ("e", [FakeRes(SHARED)])):
    try:
        client(FakeCal(FakeRes(PLAIN), others)).update_event("elfi", add_attendees=[name])
        raise SystemExit(f"expected ValueError for {name}")
    except ValueError as e:
        print("refused:", e)

# 4b) same person as principal path and as mailto: is one match (principal wins)
DUP = SHARED.replace(b"ATTENDEE;CN=Daniel Seifert;PARTSTAT=ACCEPTED;ROLE=CHAIR", b"ATTENDEE;CN=Lea Machain;PARTSTAT=ACCEPTED:mailto:lea@example.com\r\nATTENDEE;CN=Daniel Seifert;PARTSTAT=ACCEPTED;ROLE=CHAIR")
res4 = FakeRes(PLAIN)
client(FakeCal(res4, [FakeRes(DUP)])).update_event("elfi", add_attendees=["Lea"])
ev4 = Calendar.from_ical(res4.data).walk("VEVENT")[0]
assert LEA in {str(a) for a in ev4["attendee"]}, res4.data

# 5) create_event with attendees
cal5 = FakeCal(None, [FakeRes(SHARED)])
out5 = client(cal5).create_event("Test", "2027-01-16T11:00:00Z", "2027-01-16T12:00:00Z", calendar="Privat", attendees=["Lea"])
ev5 = Calendar.from_ical(cal5.created).walk("VEVENT")[0]
assert str(ev5["organizer"]) == DAN and len(ev5["attendee"]) == 2, out5
print("ALL OK")
