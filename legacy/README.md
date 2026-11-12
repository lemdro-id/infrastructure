# Legacy Fly apps (not running)

These directories describe the original all-on-Fly backend. Both apps are **suspended on Fly with 0 machines**:

- `lemmy/` → Fly app `lemdroid-lemmy` (Lemmy 0.19.3 behind a Go health proxy)
- `postgres/` → Fly app `lemdroid-postgres` (Fly Postgres)
- `pictrs/` → Fly app `lemdroid-pictrs` (pict-rs 0.4.6, sled repo on a Fly volume), replaced by pict-rs 0.5 on the VPS

The Lemmy backend and its PostgreSQL database now run on a dedicated VPS, which the Fly apps reach over a
private WireGuard peer in the Fly private network. See [../docs/architecture.md](../docs/architecture.md).

Kept for history; they'll be deleted once the suspended Fly apps are destroyed.
