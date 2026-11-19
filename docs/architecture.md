# lemdro.id architecture (as of 2026-11-19)

Fly.io was retired on 2026-11-19. Everything now runs on one backend server behind Cloudflare.

## Overview
```
User / fediverse ──► Cloudflare (zone lemdro.id, Free plan)
   │
   ├─ m. / a. / alexandrite. / p. / nu. / photon.lemdro.id
   │     └─► Cloudflare Workers static assets (Voyager, Alexandrite, Photon). No origin; DNS is proxied AAAA 100::
   │
   └─ lemdro.id / l.lemdro.id / old.lemdro.id
         └─► Cloudflare Tunnel `lemdroid-ovh` (outbound-only cloudflared on the server)
               └─► Backend server (OVH, Debian 13)
                     ├─ nginx (Docker, host network, 127.0.0.1:8088)       box/frontends/nginx.conf
                     │    ├─ lemdro.id: /inbox, /api, /pictrs, /feeds, nodeinfo, .well-known,
                     │    │   ActivityPub (by Accept header) and every non-GET ──► Lemmy 127.0.0.1:8080
                     │    │   everything else ──► Photon static files (/srv/photon, internal 127.0.0.1:8089)
                     │    ├─ l.lemdro.id   ──► lemmy-ui 127.0.0.1:1234 (/api → Lemmy)
                     │    └─ old.lemdro.id ──► mlmym 127.0.0.1:8081
                     ├─ Lemmy 0.19.21 (Docker Compose, host network, 127.0.0.1:8080)
                     ├─ pict-rs 0.5 (Docker Compose, 127.0.0.1:8180) ──► Backblaze B2
                     └─ PostgreSQL 16 (native; lemmy + pictrs DBs)
```

## Cloudflare
- **DNS:** `lemdro.id`, `l.` and `old.` are proxied CNAMEs to the tunnel (`<tunnel-id>.cfargotunnel.com`).
  The Worker hosts are proxied `AAAA 100::`; `a.`, `p.` and `photon.` are CNAMEs to `alexandrite.` and `nu.`.
  `staging.lemdro.id` is separate (outside this setup).
- **Tunnel `lemdroid-ovh`:** remotely managed. Ingress: `lemdro.id`, `l.lemdro.id` and `old.lemdro.id` go to `http://127.0.0.1:8088`; everything else gets 404.
  The server runs it as systemd unit `cloudflared-lemdroid` (`box/frontends/cloudflared-lemdroid.service`, metrics on
  `127.0.0.1:20241`). The token lives only on the server in a root-only file. There are no inbound firewall openings.
- **Workers (static assets only, no script, free):** `lemdroid-voyager` (m.), `lemdroid-alexandrite` (a., alexandrite.),
  `lemdroid-photon` (p., nu., photon.). Each is attached by zone routes `host/*`. SPA fallback, `_headers` for caching.
- **Security:** a custom WAF rule puts a Managed Challenge on `old.` and `l.`. Config rules: Rocket Loader off for l./a.; relaxed security
  for lemmy.world's IP. SSL Full (strict) applies to the Worker hosts; tunnel hosts need no origin certificate.
- **Real client IP:** Cloudflare sends `CF-Connecting-IP`; box nginx trusts it from loopback (cloudflared) and passes
  `X-Forwarded-For`/`X-Real-IP` to Lemmy, which rate-limits per client. mlmym talks to `lemdro.id` itself, so all
  old. users share one rate-limit bucket. This is the same as it was on Fly.

## Backend server (not yet fully managed in this repo)
- Debian 13, 16 threads, 31 GB RAM. Frontends compose project: `box/frontends/` (nginx, lemmy-ui, mlmym; images pinned by digest).
- **Lemmy 0.19.21** via Docker Compose (host networking), bound to `127.0.0.1:8080` only. Its `config.hjson` (secrets) isn't stored here.
- **pict-rs 0.5** via Docker Compose (`pictrs/`), `127.0.0.1:8180`; Lemmy proxies `/pictrs` to it. Metadata in the `pictrs` database, media in Backblaze B2.
- **PostgreSQL 16** (native), local only.
- Federation: inbound comes through the tunnel at `/inbox`; outbound leaves from the server directly.
- The Fly WireGuard link (`fly0`) is disabled. Its config is kept on the server only as an archive.

## Backups
- PostgreSQL: a nightly logical `pg_dump` of `lemmy` and `pictrs` (9 PM Pacific), pulled to an off-site server (operator-run). That server's own backups are copied offsite weekly.
- pict-rs media: Backblaze B2.

## Retired: Fly.io (2026-11-19)
The org `lemdroid` and every app were deleted: proxy, lemmy-ui, photon-ui, voyager, mlmym, alexandrite-ui,
federation-buffer, the legacy Lemmy and Postgres, and the remote builder. The `fly.toml` directories in this repo are kept
for history and as a rebuild reference only; nothing deploys them.

## Not yet captured here (roadmap)
1. Server configuration as code (OS, Postgres, Lemmy compose, cloudflared, nftables), likely via Ansible.
2. Cloudflare as code (DNS, tunnel ingress, Worker routes, WAF/config rules) and the Worker asset build scripts.
3. CI: config validation and a drift report.
4. Per-PR staging.
