# Offline test: sent mail gets a Message-ID, is logged, and a copy is appended
# to the Sent folder (and a failing copy doesn't fail the send):
#   python tests/test_sent_copy.py
import email
import sys
from email import policy
from types import SimpleNamespace

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from icloud_mcp import mail as mailmod
from icloud_mcp.config import Config


class FakeSMTP:
    sent = []

    def __init__(self, *a):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg, to_addrs):
        FakeSMTP.sent.append((msg, to_addrs))


class FakeBox:
    appended = []
    folders = [SimpleNamespace(name="INBOX", flags=("\\HasNoChildren",)),
               SimpleNamespace(name="Sent Messages", flags=("\\HasNoChildren", "\\Sent"))]
    fail = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def folder(self):
        return SimpleNamespace(list=lambda: FakeBox.folders)

    def append(self, data, folder, dt=None, flag_set=None):
        if FakeBox.fail:
            raise RuntimeError("IMAP down")
        FakeBox.appended.append((data, folder, flag_set))


mailmod.smtplib.SMTP = FakeSMTP
cfg = Config(apple_id="id@example.com", apple_pw="x", bearer_token="t", imap_email="me@icloud.com",
             mail_from="me@icloud.com", mail_from_aliases=("dan@seifert.id",))
client = mailmod.MailClient(cfg)
client._box = lambda: FakeBox()

r = client.send(["shop@example.com"], "Garantie", "Hallo", from_address="dan@seifert.id",
                attachments=[("r.pdf", "application/pdf", b"%PDF-x")])
assert r["sent"] and r["saved_to_sent"] == "Sent Messages" and "sent_copy_error" not in r, r
assert r["message_id"].startswith("<") and r["message_id"].endswith("@seifert.id>"), r["message_id"]
data, folder, flags = FakeBox.appended[-1]
assert folder == "Sent Messages" and flags and "SEEN" in str(flags[0]).upper()
copy = email.message_from_bytes(data, policy=policy.default)
sent_msg, _ = FakeSMTP.sent[-1]
assert copy["Message-ID"] == r["message_id"] == sent_msg["Message-ID"]
assert copy["Date"] and copy["From"] == "dan@seifert.id"
assert [p.get_filename() for p in copy.iter_attachments()] == ["r.pdf"]

# explicit SENT_FOLDER wins
client2 = mailmod.MailClient(Config(apple_id="a", apple_pw="x", bearer_token="t", mail_from="me@icloud.com",
                                    sent_folder="Gesendet"))
client2._box = lambda: FakeBox()
assert client2.send(["x@example.com"], "s", "b")["saved_to_sent"] == "Gesendet"

# no \Sent flag: iCloud's default name
FakeBox.folders = [SimpleNamespace(name="INBOX", flags=())]
assert client.send(["x@example.com"], "s", "b")["saved_to_sent"] == "Sent Messages"

# copy fails: the mail is still reported as sent, with the error
FakeBox.fail = True
r = client.send(["x@example.com"], "s", "b")
assert r["sent"] and r["saved_to_sent"] is None and "IMAP down" in r["sent_copy_error"], r
print("ok")
