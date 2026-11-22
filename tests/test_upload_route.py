# Offline test of POST /attachments (auth, file name, size cap) and the tool
# list: python tests/test_upload_route.py  (needs httpx)
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from starlette.testclient import TestClient

from icloud_mcp import server as srv
from icloud_mcp.config import Config

cfg = Config(apple_id="id@example.com", apple_pw="x", bearer_token="tok", mail_from="me@icloud.com",
             mail_from_aliases=("dan@seifert.id",), attachment_max_bytes=1000)
mcp = srv.build(cfg)
app = mcp.streamable_http_app()
app.add_middleware(srv.BearerAuth, token=cfg.bearer_token)
srv.add_upload_route(app, cfg, mcp._icloud_store)
c = TestClient(app)
auth = {"Authorization": "Bearer tok"}

assert c.post("/attachments?filename=a.pdf", content=b"x").status_code == 401
r = c.post("/attachments?filename=../a.pdf", content=b"%PDF", headers={**auth, "Content-Type": "application/pdf"})
assert r.status_code == 200 and r.json()["filename"] == "a.pdf", r.text
assert mcp._icloud_store.get(r.json()["id"]).content_type == "application/pdf"
assert c.post("/attachments?filename=b", content=b"x" * 2000, headers=auth).status_code == 413
assert c.post("/attachments?filename=e", content=b"", headers=auth).status_code == 400
tools = [t.name for t in mcp._tool_manager.list_tools()]
assert "mail_send" in tools and "mail_senders" in tools, tools
print("ok")
