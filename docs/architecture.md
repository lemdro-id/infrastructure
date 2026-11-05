# lemdro.id architecture (as of 2026-11)

## Overview
```
User / fediverse ──► Cloudflare ──► Fly.io edge
                                     ├─ lemdroid-lemmy-proxy (lemdro.id, nginx; iad / fra / sjc)
                                     │    ├─ UI requests        ─► frontend apps (flycast)
                                     │    ├─ /inbox             ─► federation-buffer ─┐
                                     │    └─ /api, /pictrs, ActivityPub, nodeinfo ───┤
                                     ├─ lemmy-ui, photon, voyager, mlmym, alexandrite │ (own subdomains)
                                     └─ lemdroid-pictrs (private) ◄──────────────────┤──► Backblaze B2
                                                                                      ▼
                                   Fly private network (6PN) ══ WireGuard peer ══► Backend VPS
                                                                                   ├─ Lemmy 0.19.21 (Docker Compose)
                                                                                   └─ PostgreSQL 16
```

## Fly.io (org `lemdroid`)
- **Entry:** `lemdroid-lemmy-proxy` serves `lemdro.id` and routes UI traffic to frontends, `/inbox` to `federation-buffer`, and API, pict-rs and federation traffic to the Lemmy backend.
- **Frontends:** lemmy-ui, Photon, Voyager, mlmym, Alexandrite, each with its own subdomain, autostopping when idle.
- **federation-buffer:** always-on Go service that accepts inbound federation and forwards it to Lemmy, so inbound activity isn't dropped during backend restarts.
- **pict-rs:** private only (flycast). 0.4.6 with a sled metadata repo on a Fly volume; media in Backblaze B2. Upgrade to 0.5 + Postgres repo planned (#7).
- Fly apps reach the backend at a fixed private 6PN address (see `LEMMY_UI_LEMMY_INTERNAL_HOST` / `FORWARD_HOST`).

## Backend VPS (not yet managed in this repo)
- Debian 12 VPS joined to the Fly private network as a **WireGuard peer** (the `fly wireguard create` mechanism). Lemmy listens only on that private address.
- **Lemmy 0.19.21** via Docker Compose (host networking). Its `config.hjson` (secrets) isn't stored here.
- **PostgreSQL 16** (native), local to Lemmy.
- Outbound federation leaves from the VPS directly.

## Backups
- PostgreSQL: continuous WAL streaming plus weekly full backups with **barman** to a server off-site from the VPS (operator-run). It's also included in that server's own nightly backups.
- pict-rs metadata: Fly volume snapshots (daily, 5-day retention). Media: Backblaze B2.

## Not yet captured here (roadmap)
1. VPS configuration as code (OS, Postgres config/pg_hba, Lemmy compose, WireGuard peer), likely via Ansible.
2. CI: config validation, tests, a drift report against live Fly, then approved deploys.
3. Per-PR staging environments (ephemeral Fly apps + throwaway seeded DB, federation disabled).
4. Cloudflare and Backblaze settings.
