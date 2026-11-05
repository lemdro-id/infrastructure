# Secrets (names only, never values)

Set with `fly secrets set -a <app> NAME=...`. Nothing in this repo contains secret values.

| App | Secrets |
|---|---|
| lemdroid-pictrs | `PICTRS__SERVER__API_KEY`, `PICTRS__STORE__ACCESS_KEY`, `PICTRS__STORE__SECRET_KEY` |
| lemdroid-lemmy-proxy | none |
| federation-buffer | none |
| lemdroid-lemmy-ui | none |
| lemdroid-photon-ui | none |
| lemdroid-voyager | none |
| lemdroid-mlmym | none |
| lemdroid-alexandrite-ui | none |
| lemdroid-lemmy (legacy, suspended) | `LEMMY_DATABASE_URL`, `LEMMY_SMTP_PASSWORD` |
| lemdroid-postgres (legacy, suspended) | `FLY_CONSUL_URL`, `OPERATOR_PASSWORD`, `REPL_PASSWORD`, `SSH_CERT`, `SSH_KEY`, `SU_PASSWORD` |

Backend VPS secrets (Lemmy `config.hjson`, database passwords, WireGuard keys) live only on that host.
