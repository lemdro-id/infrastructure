# pict-rs

pict-rs 0.5 runs on the backend VPS next to Lemmy (Docker Compose, host networking, `127.0.0.1:8180` only),
with its metadata in the PostgreSQL database `pictrs` and media in Backblaze B2 (bucket `lemdroid`).
Lemmy's `config.hjson` points `pictrs.url` at `http://127.0.0.1:8180/`.

Deploy (on the VPS):
```sh
cd /root/pictrs && docker compose pull && docker compose up -d
```

Secrets (names only) are in `pictrs.env.example`; values live only in `/root/pictrs/pictrs.env` on the VPS.

The old Fly app `lemdroid-pictrs` (0.4.6, sled repo on a Fly volume) is kept in `legacy/pictrs/` for history.
