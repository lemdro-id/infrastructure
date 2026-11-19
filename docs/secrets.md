# Secrets (names only, never values)

Nothing in this repo contains secret values.

| Where | Secrets |
|---|---|
| Backend server: Lemmy `config.hjson` | database URL, SMTP password, and the rest of Lemmy's config secrets |
| Backend server: pict-rs `/root/pictrs/pictrs.env` | names in `pictrs/pictrs.env.example` (API key, B2 access/secret key) |
| Backend server: `/etc/cloudflared/lemdroid-ovh.token` (root 600) | Cloudflare Tunnel token for `lemdroid-ovh` |
| Backend server: PostgreSQL | role passwords |
| Cloudflare | account API tokens (held by operators, not on the server) |

Frontends (nginx, lemmy-ui, mlmym, and the Workers) need no secrets.
