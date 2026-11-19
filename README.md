# Infrastructure
Repository hosting the configuration which informs the infrastructure which runs https://lemdro.id

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together today and
[docs/secrets.md](docs/secrets.md) for which secrets exist (names only).

Since 2026-11-19 everything runs on one backend server behind Cloudflare (Tunnel + Workers static assets). Fly.io is retired.

## Layout
| Directory | Runs as | What it is |
|---|---|---|
| `box/frontends/` | backend server, Docker Compose + systemd | nginx entrypoint for `lemdro.id` / `l.` / `old.`, lemmy-ui, mlmym, cloudflared unit |
| `pictrs/` | backend server, Docker Compose | pict-rs 0.5 image service (localhost only), metadata in Postgres, media in Backblaze B2 |
| `proxy/` | retired (Fly `lemdroid-lemmy-proxy`) | old Fly nginx entrypoint; its routing now lives in `box/frontends/nginx.conf` |
| `federation-buffer/` | retired | old `/inbox` buffer |
| `lemmy-ui/` | retired (Fly) | now `box/frontends` (`l.lemdro.id`) |
| `photon-ui/` | retired (Fly) | now Workers static assets (`p.`, `nu.`, `photon.`) and box nginx (`lemdro.id` root) |
| `voyager/` | retired (Fly) | now Workers static assets (`m.lemdro.id`) |
| `mlmym/` | retired (Fly) | now `box/frontends` (`old.lemdro.id`) |
| `alexandrite-ui/` | retired (Fly) | now Workers static assets (`a.`, `alexandrite.`) |
| `anubis-disabled/` | not deployed | Anubis builds of mlmym and lemmy-ui; see its README |
| `legacy/` | retired | old in-Fly Lemmy backend and Fly Postgres |

## Postgres
Postgres runs natively on the backend server next to Lemmy (local only); that host is not yet fully managed from this repo.
