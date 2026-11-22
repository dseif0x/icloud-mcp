# Offline test of mail_send's From aliases and uploaded attachments:
#   python tests/test_mail_attachments.py
import email
import sys
from email import policy

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from icloud_mcp import mail as mailmod
from icloud_mcp.attachments import AttachmentStore, safe_filename
from icloud_mcp.config import Config

sent = []


class FakeSMTP:
    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, pw):
        self.user = user

    def send_message(self, msg, to_addrs):
        sent.append((msg, to_addrs))


mailmod.smtplib.SMTP = FakeSMTP
cfg = Config(apple_id="id@example.com", apple_pw="x", bearer_token="t", imap_email="me@icloud.com",
             mail_from="me@icloud.com", mail_from_aliases=("dan@seifert.id",))
client = mailmod.MailClient(cfg)

# file names: no paths or odd characters
assert safe_filename("../../etc/passwd") == "passwd"
assert safe_filename("C:\\x\\Rechnung 2024 (1).pdf") == "Rechnung 2024 _1_.pdf"
assert safe_filename("") == "attachment"

# store: put/get/pop, size cap, expiry
store = AttachmentStore(ttl_seconds=3600, max_bytes=100)
meta = store.put("invoice.pdf", "application/pdf", b"%PDF-1.7 hello")
assert store.get(meta["id"]).data == b"%PDF-1.7 hello"
try:
    store.put("big.bin", "application/octet-stream", b"x" * 100)
    raise AssertionError("size cap not enforced")
except ValueError:
    pass
expired = AttachmentStore(ttl_seconds=-1, max_bytes=100)
eid = expired.put("a.txt", "text/plain", b"a")["id"]
try:
    expired.get(eid)
    raise AssertionError("expiry not enforced")
except KeyError:
    pass

# From: alias accepted (case-insensitive), others rejected
assert client.allowed_from() == ["me@icloud.com", "dan@seifert.id"]
try:
    client.send(["x@example.com"], "s", "b", from_address="evil@example.com")
    raise AssertionError("unknown From accepted")
except ValueError as e:
    assert "dan@seifert.id" in str(e)

a = store.get(meta["id"])
r = client.send(["shop@example.com"], "Garantieanfrage", "Guten Tag", from_address="Dan@Seifert.id",
                attachments=[(a.filename, a.content_type, a.data)])
assert r["from"] == "Dan@Seifert.id" and r["attachments"] == ["invoice.pdf"], r
msg, rcpt = sent[-1]
parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
assert parsed["From"] == "Dan@Seifert.id" and rcpt == ["shop@example.com"]
parts = list(parsed.iter_attachments())
assert len(parts) == 1 and parts[0].get_filename() == "invoice.pdf"
assert parts[0].get_content_type() == "application/pdf" and parts[0].get_content() == b"%PDF-1.7 hello"
assert parsed.get_body(("plain",)).get_content().strip() == "Guten Tag"

# default sender without from_address, no attachments
r = client.send(["x@example.com"], "s", "b")
assert r["from"] == "me@icloud.com" and r["attachments"] == []

print("ok")
