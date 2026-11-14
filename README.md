# iCloud MCP

A small [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes **iCloud Calendar** (CalDAV) and **iCloud Mail** (IMAP/SMTP) as tools
over **Streamable HTTP**, guarded by a static bearer token. Built to run as a
networked service (e.g. in Kubernetes) so the Apple credentials stay in one
place and clients only hold the server URL + token.

> **Reminders are out of scope.** Modern iCloud Reminders aren't reachable over
> standard CalDAV (Apple "upgraded" the lists); reaching them reliably needs a
> Mac/AppleScript or the private CloudKit API. This server sticks to Calendar
> and Mail, which work cleanly over open protocols.

## Tools

| Tool | What it does |
|---|---|
| `cal_list_calendars` | List the account's calendars |
| `cal_create_event` | Create an event (ISO times or all-day, optional reminders, optional attendees) |
| `cal_list_events` | List events in a time range (with organizer and attendees) |
| `cal_update_event` | Change fields of an event in place by UID; attendees, alarms etc. stay (shared events keep their invitees); `add_attendees` / `remove_attendees` invite or drop people |
| `cal_delete_event` | Delete an event by UID |
| `mail_list_folders` | List IMAP folders |
| `mail_search` | Search a folder (unseen / since / from / subject / text) |
| `mail_get` | Fetch a full message (body + attachment list) |
| `mail_send` | Send a plain-text email |

Disable any tool with `ICLOUD_MCP_DISABLED_TOOLS` (comma-separated), e.g.
`ICLOUD_MCP_DISABLED_TOOLS=mail_send`.

## Configuration (environment)

| Var | Required | Default |
|---|---|---|
| `APPLE_ID` | yes | — (your Apple ID email) |
| `APPLE_APP_PW` | yes | — ([app-specific password](https://appleid.apple.com)) |
| `MCP_BEARER_TOKEN` | yes | — (token clients must present) |
| `CALDAV_URL` | no | `https://caldav.icloud.com` |
| `IMAP_HOST` / `IMAP_PORT` | no | `imap.mail.me.com` / `993` |
| `SMTP_HOST` / `SMTP_PORT` | no | `smtp.mail.me.com` / `587` |
| `ICLOUD_MCP_DISABLED_TOOLS` | no | — |
| `HOST` / `PORT` | no | `0.0.0.0` / `8080` |

Create the app-specific password at appleid.apple.com → *Sign-In and Security →
App-Specific Passwords* (requires 2FA). It is revocable there at any time.

## Run

```bash
pip install -r requirements.txt
APPLE_ID=you@icloud.com APPLE_APP_PW=xxxx-xxxx-xxxx-xxxx MCP_BEARER_TOKEN=$(openssl rand -hex 24) \
  python -m icloud_mcp
# MCP endpoint: http://localhost:8080/mcp   health: /healthz
```

Docker:

```bash
docker build -t icloud-mcp .
docker run -p 8080:8080 -e APPLE_ID=... -e APPLE_APP_PW=... -e MCP_BEARER_TOKEN=... icloud-mcp
```

## Endpoints

- `POST /mcp` — Streamable HTTP MCP (requires `Authorization: Bearer <token>`)
- `GET /healthz` — unauthenticated liveness/readiness probe

## Client config

Any MCP client that supports a remote HTTP server, e.g.:

```json
{ "type": "http", "url": "http://icloud-mcp.mcp:8080/mcp",
  "headers": { "Authorization": "Bearer <MCP_BEARER_TOKEN>" } }
```

## Security notes

- An app-specific password grants broad iCloud access (mail/calendar/contacts)
  over DAV/IMAP; the control is instant revocation at appleid.apple.com.
- Keep the Apple password only in the server's secret — clients never see it.
- The bearer token is the only thing standing in front of your mailbox; treat it
  like a password and serve the endpoint on a trusted network.

See [`deploy/`](deploy/) for example Kubernetes manifests.
