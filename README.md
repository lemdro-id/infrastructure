# Infrastructure
Repository hosting the configuration which informs the infrastructure which runs https://lemdro.id

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together today,
[docs/secrets.md](docs/secrets.md) for which secrets exist (names only), and
[docs/PATCHES.md](docs/PATCHES.md) for local band-aid patches (Lemmy activity counts, Photon Explore sort,
and Cloudflare rules that are documented here but not managed from this repo).

Since 2026-11-19 everything runs on one backend server behind Cloudflare (Tunnel + Workers static assets).

## Layout
| Directory | Runs as | What it is |
|---|---|---|
| `box/frontends/` | backend server, Docker Compose + systemd | nginx entrypoint for `lemdro.id` / `l.` / `old.`, lemmy-ui, mlmym, cloudflared unit |
| `pictrs/` | backend server, Docker Compose | pict-rs 0.5 image service (localhost only), metadata in Postgres, media in Backblaze B2 |

## Postgres
Postgres runs natively on the backend server next to Lemmy (local only); that host is not yet fully managed from this repo.
