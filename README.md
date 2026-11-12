# Infrastructure
Repository hosting the configuration which informs the infrastructure which runs https://lemdro.id

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together today and
[docs/secrets.md](docs/secrets.md) for which secrets each app expects (names only).

## Layout
| Directory | Fly app | What it is |
|---|---|---|
| `proxy/` | `lemdroid-lemmy-proxy` | nginx entrypoint for `lemdro.id` |
| `federation-buffer/` | `federation-buffer` | buffers inbound ActivityPub `/inbox` traffic in front of Lemmy |
| `lemmy-ui/` | `lemdroid-lemmy-ui` | official lemmy-ui (`l.lemdro.id`) |
| `photon-ui/` | `lemdroid-photon-ui` | Photon (`p.`, `nu.`, `photon.lemdro.id`) |
| `voyager/` | `lemdroid-voyager` | Voyager (`m.lemdro.id`) |
| `mlmym/` | `lemdroid-mlmym` | old-reddit style UI (`old.lemdro.id`) |
| `alexandrite-ui/` | `lemdroid-alexandrite-ui` | Alexandrite (`a.lemdro.id`) |
| `pictrs/` | backend VPS (Compose) | pict-rs 0.5 image service (localhost only), metadata in Postgres, media in Backblaze B2 |
| `legacy/` | suspended | old in-Fly Lemmy backend and Fly Postgres |

## Postgres
Postgres is no longer on Fly. It runs on the backend VPS alongside Lemmy; that host is not yet managed from this repo.
