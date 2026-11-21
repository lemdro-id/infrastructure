# Status page (status.lemdro.id)

lemdro.id has a public status page at **https://status.lemdro.id**.

## How it works

- **Uptime Kuma** (2.x) runs on a small container on the admins' own hardware, separate from the lemdro.id server, so it
  keeps reporting when lemdro.id itself is down.
- It is published through a reverse proxy behind Cloudflare. Only the public status page, its read-only API, badges and
  static assets are reachable from the internet; the Kuma admin UI is only reachable from the admins' private network.
- Origin TLS uses a Cloudflare Origin CA certificate (zone SSL mode Full (strict)).

## What is checked (every 60 s; a service is marked down after 3 failed checks in a row)

| Service | Check |
|---|---|
| Website | `https://lemdro.id/` returns 200 |
| API | `/api/v3/site` returns the Lemmy version |
| Federation (nodeinfo) | `/.well-known/nodeinfo` advertises NodeInfo 2.1 |
| Federation (seen from lemmy.world) | lemmy.world's API still resolves `!android@lemdro.id` (every 5 min) |
| Photon, Alexandrite, Voyager | each frontend's home page loads |
| Images (pict-rs) | a known image thumbnail under `/pictrs/image/` loads, with a cache-buster so Cloudflare's cache is bypassed |
| External check | see below |

`l.lemdro.id` and `old.lemdro.id` are not on the page: they sit behind a Cloudflare managed challenge, which an uptime
checker cannot pass.

## External check

A small Cloudflare Worker (`lemdroid-status-external`) runs every 5 minutes from Cloudflare's edge. It checks the
front page, the API and NodeInfo, plus whether the status page itself is reachable, stores the last result in Workers KV
and serves it as read-only JSON on its workers.dev URL. The status page shows it as "External check (Cloudflare)".

If status.lemdro.id is unreachable but the Worker JSON says `"core_ok": true`, the problem is on the status page's side
(its host or network), not lemdro.id.

## Not managed by this repo

The status page host, its reverse proxy entry, the DNS record and the Worker are managed outside this playbook. No
Ansible role touches them, so a playbook run does not change or revert them.
