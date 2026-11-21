# lemdro.id local patches

Deviations from stock Lemmy 0.19.21, Photon v2.4.3, and the roles in this repository, as they run on the backend server (lemdroid-ovh).

Last updated 20 November 2026, 16:00 CET (Europe/Berlin). The server clock is UTC.

Check everything that lives on the server with `sudo lemdroid-patch-check` (read-only; exits non-zero if anything has drifted). Cloudflare-only items are documented here and are **not** installed, updated, or checked by Ansible or by that script. Change them in the Cloudflare dashboard or API.

The `lemdroid_patches` role installs sections 1 and 2: the SQL and scripts, logrotate, the checker, and — only when `lemdroid_start_services` is true — the cron jobs, plus a one-shot apply of the now() fix. The Photon Explore patch (section 3) is recorded under `ansible/roles/lemdroid_patches/photon/` but is not deployed by the playbook. AndroidNews v2 and the Valnet feed-proxy Worker source (sections 4 and 5) are managed by the `androidnews` role.

Before any Lemmy upgrade, read sections 1 and 2 and remove or refresh those hooks so they do not run against a new schema.

---

## 1. Lemmy activity functions use now() instead of a frozen 'now' (database, on the server)

- **What:** `r.community_aggregates_activity(text)` and `r.site_aggregates_activity(text)` (owner `lemmy`). The only change is `'now'::timestamp` → `now()::timestamp` in eight places; types and casts are unchanged. The original and patched bodies are in `/usr/local/lib/lemdroid/now-fix/` (and in this repo under the role's `files/now-fix/`).
- **Why:** In plpgsql, `'now'::timestamp` is folded into the cached plan on the first call per database session, so Lemmy's pooled connections compute "active users" over windows anchored at whenever that connection first ran the job. That made `users_active_*` wrong (inflated, and sometimes day greater than week) and fought the active-zero cron in section 2. Confirmed 20 November 2026 with auto_explain: the old version froze at the first call's time; the patched one uses `now()`.
- **Applied:** 20 November 2026, 15:39 CET (Europe/Berlin).
- **Checksums** (`md5(prosrc)`):
  - community: original `93ae0ba6935c865ab791417ba06fdbd7` → patched `a60f33a66c248ded16263a07bb6a6016`
  - site: original `313d8fa49e71e75cc096708aa8f16ce6` → patched `fa67565ed015aafda650835f706a7387`
- **Reapply hook:** `/etc/cron.d/lemdroid-now-fix` (every 5 minutes, user `postgres`, flock) runs `/usr/local/lib/lemdroid/reapply-now-fix.sh`, logging to `/var/log/lemdroid-now-fix.log` (logrotate: `/etc/logrotate.d/lemdroid-now-fix`). If the body is already patched, it does nothing. If it matches the original checksum, it reapplies. Anything else writes a `!!!ALERT!!!` line to the log and syslog (tag `lemdroid-now-fix`), exits 2, and does not apply. `reapply-now-fix.sh status` is read-only.
- **When Lemmy reverts it:** Lemmy 0.19.21 re-creates schema `r` only when there are pending migrations (an upgrade), not on a plain restart. A container restart on 20 November 2026 at 15:45 CET kept the patch. A simulated revert at 15:46 CET was re-fixed by the cron at 15:50 CET.
- **Undo:**

      sudo rm /etc/cron.d/lemdroid-now-fix /etc/logrotate.d/lemdroid-now-fix
      sudo cp /root/backup-explore-fix-20261120/restore-orig.sql /tmp/ && sudo chmod 644 /tmp/restore-orig.sql
      sudo -u postgres psql -d lemmy -X -f /tmp/restore-orig.sql

  The restore script reads the `.orig.sql` files in `/usr/local/lib/lemdroid/now-fix`. Optionally then remove `/usr/local/lib/lemdroid/now-fix`, `reapply-now-fix.sh`, and the log. To stop Ansible putting them back, remove this role from the playbook.
- **Obsolete when:** Lemmy upstream stops using `'now'::timestamp` in these functions (check `utils.sql` of the new version; 1.0 rewrote this area, but as of 1.0 beta 3 the frozen-timestamp bug was still present). After an upgrade the hook will ALERT if the body is unknown: compare, then either delete the hook or regenerate the `.patched.sql` files and checksums for the new body.

## 2. Hourly zeroing of stale community `users_active_*` (database and cron, on the server)

- **What:** `/etc/cron.d/lemdroid-explore-active-zero`, hourly at minute 17, user `postgres`, flock, runs `/usr/local/lib/lemdroid/zero-stale-active.sql` and logs to `/var/log/lemdroid-explore-active-zero.log`. It sets `users_active_{day,week,month,half_year}` to 0 for **local** communities only, and only where Lemmy's own definition (a non-bot post, comment, post vote, or comment vote in the window) finds nothing. It never writes a non-zero value. A run takes about 0.2 seconds.
- **Why:** Lemmy's scheduled job only updates communities that had activity, so quiet ones kept old counts forever (for example `!sony` showed 17 with no posts since April 2026) and floated up Explore's Top sorts.
- **Applied:** one-time run 20 November 2026, 14:56 CET (Europe/Berlin) (54 values across 24 communities); cron from 14:57 CET.
- **Backup:** `/root/backup-explore-fix-20261120/community_aggregates_active_before.csv` and `undo-explore-active.sql`.
- **Undo:**

      sudo rm /etc/cron.d/lemdroid-explore-active-zero /etc/logrotate.d/lemdroid-explore-active-zero /usr/local/lib/lemdroid/zero-stale-active.sql

  To restore the old values (optional, after removing the cron):

      sudo cp /root/backup-explore-fix-20261120/{community_aggregates_active_before.csv,undo-explore-active.sql} /tmp/
      sudo chmod 644 /tmp/community_aggregates_active_before.csv /tmp/undo-explore-active.sql
      sudo -u postgres psql -d lemmy -X -f /tmp/undo-explore-active.sql

- **Not covered:** remote communities keep stale counts. Active and Hot community sorts are still a `hot_rank = 0` tie (a Lemmy 0.19 bug).
- **Obsolete when:** Lemmy writes zeros for quiet communities itself (this was fixed in the 1.0 betas but not backported to 0.19). Remove the cron before any schema-changing upgrade. The script stops on error, so it will not write bad data, but it will log errors every hour until removed.

## 3. Photon Explore default sort TopWeek (build patch; server and Cloudflare Worker)

- **What:** Photon v2.4.3 has no setting for the Explore default sort (`TopDay` is hard-coded). The deployed static build was patched: `|| "TopDay"` → `|| "TopWeek"` in the Explore load function, which meant renaming a chunk and the app entry, updating `index.html` (including its CSP hash) and `service-worker.js` (new cache name `cache-1795088067009-tw1`). The old files were kept so open tabs keep working. `version.json` is unchanged. A unified diff of the deployed build and a source-level script for future builds are in `ansible/roles/lemdroid_patches/photon/` (not deployed by Ansible). Source maps still mention `TopDay`.
- **Why:** With honest activity counts, TopWeek puts busy communities first. TopDay was dominated by stale or quiet ones; Active is broken on 0.19.21 (see the notes at the end of section 2).
- **Where:**
  - Server: `/srv/photon` (bare lemdro.id, served by frontends-nginx on 127.0.0.1:8089), installed 20 November 2026, 15:00 CET (Europe/Berlin). Backup: `/root/backup-explore-fix-20261120/srv-photon-before.tgz`.
  - Cloudflare (not on the server, not managed by Ansible): Worker `lemdroid-photon` (routes `p.`, `nu.`, `photon.`) version `1f4c2b54-c99b-46d1-a4db-e44eb3bf06d3`, deployed 20 November 2026, 14:58 CET. Previous version, for rollback: `f8c14a68-15cb-48f6-9bce-b9cb2143c3dd`.
- **Undo:**
  - Server: `sudo tar -C /srv -xzf /root/backup-explore-fix-20261120/srv-photon-before.tgz photon/index.html photon/service-worker.js`
  - Cloudflare: redeploy Worker `lemdroid-photon` version `f8c14a68-15cb-48f6-9bce-b9cb2143c3dd` at 100%.
- **Removed by:** a Photon rebuild that skips this hook, or an upstream change that removes TopDay. `ansible/scripts/build-photon.sh` now runs `photon/source-patch.sh` automatically after the commit pin check. That script looks for `TopDay` in `src/routes/explore/+layout.ts` and the build still fails if TopDay is gone. Drop the patch if upstream adds a default-sort setting.

## 4. Valnet feed proxy for AndroidNews (Cloudflare Worker and bot config)

- **What:** Cloudflare Worker `androidnews-feed-proxy` (paths `/androidpolice` and `/xda` only, 10-minute cache), reached at `https://androidnews-feed-proxy.corvettecole.workers.dev/`. Source lives in this repo at `ansible/roles/androidnews/worker/feed-proxy.js`. Ansible does not deploy the Worker. AndroidNews v2's `config.yaml` points the androidpolice-news and xda-news URL fields at it.
- **Why:** Android Police and XDA (Valnet) drop every request from the server's egress IP, regardless of user agent.
- **Undo:** point those two `url` fields in `config.yaml` back at the sites (`https://www.androidpolice.com/feed/news/` and `https://www.xda-developers.com/feed/news/`) and delete the Worker in Cloudflare. The feeds will fail from this server again until Valnet unblocks the server's egress IP (test with a fetch of those feeds from the box) or the sources are dropped.

## 5. AndroidNews v2 (server cron; managed by the androidnews role)

- **What:** `/etc/cron.d/android-news-bot` runs `*/15 * * * * androidnews /opt/android-news-bot/v2/run.sh`. v1 files stay under `/opt/android-news-bot/` for rollback. This is now the `androidnews` role in this repository, not a local deviation. Live since 20 November 2026, 13:21 CET (Europe/Berlin).
- **Note:** on the server, `v2/run.sh` is currently owned by `androidnews`; the role installs it as `root:root`. The next playbook run of `androidnews` will correct the ownership. Only one version of the bot may ever run (double posts). The cron is installed only when `lemdroid_start_services` is true.

## 6. Cloudflare WAF custom rules (Cloudflare only; not managed here)

- **Signup-bot challenge:** a Managed Challenge on `POST /api/v3/user/register` that matches a known signup-bot fingerprint. Added 20 November 2026, 10:25 CET (Europe/Berlin). Obsolete when the bot stops or changes its fingerprint (watch firewall events and register POST volume).
- **Managed Challenge on `old.lemdro.id` and `l.lemdro.id`:** challenges all public traffic to mlmym and lemmy-ui. Added 13 November 2026 against bots that ran up a former host's bill. Obsolete when it is decided this is no longer needed (that host is gone; the current server absorbs the load).
- **Undo:** disable or delete the corresponding custom WAF rules in the Cloudflare dashboard for the lemdro.id zone. Ansible does not manage them.

## 7. Cloudflare config rules (Cloudflare only; not managed here)

- **Rocket Loader off** for `l.` and `a.`, because Rocket Loader breaks those UIs.
- **Relaxed security for lemmy.world:** an allowlisted address for lemmy.world is given a lower security level (and some features such as Rocket Loader are turned off) so its federation is not challenged. This is tied to that instance's current address: if lemmy.world changes IP, its federation may be challenged again.
- **Undo:** disable or delete the corresponding configuration rules in the Cloudflare dashboard. Ansible does not manage them.

## 8. Other static-frontend build patches (Cloudflare Workers, from the Fly retirement on 19 November 2026)

- `lemdroid-alexandrite`: Alexandrite revision 452a180 (live 0.8.20) plus an `adapter-static` patch to `svelte.config.js` so it can build as static files (upstream has no static adapter). Removed by any Alexandrite rebuild without that patch.
- `lemdroid-voyager`: stock Voyager 2.49.1 files plus `_config` with `customServers: ["lemdro.id"]` (normal config, listed for completeness).
- All three Workers have hand-written `_headers` (immutable `/_app` or `/assets`; no-cache for index, env, version, and the service worker).
- None of the Worker builds, routes, or rules are managed by Ansible yet (a "Cloudflare as code" follow-up).

## 9. Server leftovers from the Fly retirement (not active; safe to delete when convenient)

- `/etc/wireguard/fly0.conf` (`wg-quick@fly0` is disabled; the Fly peer was deleted), plus copies under `/root/fly-retire-backup-20261119/`.
- Other backup folders on the server: `/root/fly-retire-backup-20261119/`, `/root/lemdroid-prep-backup`, `/root/lemdroid-setup-backup`, `/root/d13-backup`.

## Data notes (one-off database edits; nothing to undo automatically)

- 20 November 2026, 11:38–11:45 CET (Europe/Berlin): accounts from a signup bot were deleted (9,647 `local_user`/`person` rows and dependants). A dump is at `/root/backup-bp-cleanup-20261120/`.
- 20 November 2026, 14:56 CET: `users_active_*` zeroing (section 2); the CSV backup is listed there.
