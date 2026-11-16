# lemdro.id architecture (as of 2026-11)

## Overview
```
User / fediverse ──► Cloudflare ──► Fly.io edge
                                     ├─ lemdroid-lemmy-proxy (lemdro.id, nginx; iad / fra / sjc)
                                     │    ├─ UI requests        ─► frontend apps (flycast)
                                     │    └─ /inbox, /api, /pictrs, ActivityPub, nodeinfo ─►┐
                                     ├─ lemmy-ui, photon, voyager, mlmym, alexandrite       │
                                     ├─ federation-buffer (running, not on the request      │
                                     │    path; instant rollback target for /inbox)         │
                                                                                            ▼
                                   Fly private network (6PN) ══ WireGuard peer ══► Backend VPS
                                                                                   ├─ Lemmy 0.19.21 (Docker Compose)
                                                                                   ├─ pict-rs 0.5 (Docker Compose) ──► Backblaze B2
                                                                                   └─ PostgreSQL 16 (lemmy + pictrs DBs)
```

## Fly.io (org `lemdroid`)
- **Entry:** `lemdroid-lemmy-proxy` serves `lemdro.id` and routes UI traffic to frontends, and `/inbox`, API, pict-rs and other federation traffic straight to the Lemmy backend.
- **Frontends:** lemmy-ui, Photon, Voyager, mlmym, Alexandrite, each with its own subdomain, autostopping when idle.
- **federation-buffer:** still running (always-on) but no longer on the request path as of 2026-11-14. `/inbox` goes straight to Lemmy so senders see real 5xx and can retry. The app is kept up so a proxy rollback can point `/inbox` at it again instantly.
- Fly apps reach the backend at a fixed private 6PN address (see `LEMMY_UI_LEMMY_INTERNAL_HOST` / `FORWARD_HOST`).

## Backend VPS (not yet managed in this repo)
- Debian 12 VPS joined to the Fly private network as a **WireGuard peer** (the `fly wireguard create` mechanism). Lemmy listens only on that private address.
- **Lemmy 0.19.21** via Docker Compose (host networking). Its `config.hjson` (secrets) isn't stored here.
- **pict-rs 0.5** via Docker Compose (`pictrs/`), host networking on `127.0.0.1:8180`; Lemmy proxies `/pictrs` to it. Metadata in the `pictrs` database, media in Backblaze B2.
- **PostgreSQL 16** (native), local to Lemmy and pict-rs (databases `lemmy`, `pictrs`).
- Outbound federation leaves from the VPS directly.

## Backups
- PostgreSQL: a nightly logical `pg_dump` of `lemmy` and `pictrs` (9 PM Pacific) pulled over the private network to a server off-site from the VPS (operator-run). It's included in that server's own nightly backups, which are copied offsite weekly. (Replaced barman WAL streaming + weekly fulls on 2026-11-05.)
- pict-rs metadata: the `pictrs` database, in the same nightly dump. Media: Backblaze B2.

## Not yet captured here (roadmap)
1. VPS configuration as code (OS, Postgres config/pg_hba, Lemmy compose, WireGuard peer), likely via Ansible.
2. CI: config validation, tests, a drift report against live Fly, then approved deploys.
3. Per-PR staging environments (ephemeral Fly apps + throwaway seeded DB, federation disabled).
4. Cloudflare and Backblaze settings.
