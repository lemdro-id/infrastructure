# lemdroid_patches

Records and installs the local band-aid patches that run on the backend server (lemdroid-ovh) until upstream Lemmy or Photon fixes land. The full inventory, including Cloudflare items this role does **not** manage, is [docs/PATCHES.md](../../../docs/PATCHES.md).

## What this role installs

| path | what |
|---|---|
| `files/now-fix/*.sql` | Original and patched bodies of `r.community_aggregates_activity` and `r.site_aggregates_activity` (`'now'::timestamp` → `now()::timestamp`). Installed under `/usr/local/lib/lemdroid/now-fix/`. |
| `files/reapply-now-fix.sh` | Idempotent hook: no-op if already patched, reapplies if the body matches the original checksum, alerts and does nothing if a Lemmy upgrade changed the body. |
| `files/zero-stale-active.sql` | Hourly job: sets `users_active_*` to 0 for local communities with no activity in the window. Never writes a non-zero value. |
| `files/lemdroid-patch-check` | Read-only checker (`/usr/local/bin/lemdroid-patch-check`). |
| `files/*.cron`, `files/*.logrotate` | Cron and logrotate for the two jobs. |
| `docs/PATCHES.md` (repo root) | Copied to `/usr/local/lib/lemdroid/PATCHES.md`. |
| `photon/` | Photon Explore TopWeek unified diff and `source-patch.sh`. **Not deployed** by this role. |

Scripts, SQL, logrotate, log files and the checker are always installed. The cron jobs, and a one-shot run of `reapply-now-fix.sh`, happen only when `lemdroid_start_services` is true — the same guard the `androidnews` role uses, so a configuration-only playbook run cannot start these jobs.

## Undo and when this becomes obsolete

- **now() fix:** remove the cron and logrotate, restore the original function bodies from `/root/backup-explore-fix-20261120/restore-orig.sql` (or the `.orig.sql` files). Drop or refresh the hook after a Lemmy upgrade; 1.0 rewrote this area, but as of 1.0 beta 3 the frozen-timestamp bug was still present.
- **Active-zero cron:** remove the cron, logrotate and SQL. Lemmy 1.0 already writes zeros for quiet communities, so this job can go once the server is on 1.0. Remove it before any schema-changing upgrade.
- **Photon TopWeek:** any Photon rebuild or upgrade undoes it. `ansible/scripts/build-photon.sh` still builds stock Photon (TopDay) unless you apply `photon/source-patch.sh` in the Photon checkout first. The script refuses to run if upstream no longer contains `TopDay`. On the server, restore `/srv/photon` from `/root/backup-explore-fix-20261120/srv-photon-before.tgz`. On Cloudflare, redeploy Worker `lemdroid-photon` version `f8c14a68-15cb-48f6-9bce-b9cb2143c3dd` at 100%.

Cloudflare WAF and config rules, Worker deployments, and the Valnet feed proxy are documented in `docs/PATCHES.md` only. This role does not manage them.
