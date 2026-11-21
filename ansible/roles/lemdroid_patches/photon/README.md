# Photon Explore default sort: TopDay → TopWeek (Photon v2.4.3)

These files record the patch. Ansible does **not** deploy them. `ansible/scripts/build-photon.sh` applies `source-patch.sh`. A rebuild without this hook, or an upstream change that removes TopDay, is what would undo or block it.

Live state as of 20 November 2026, 14:58–15:00 CET (Europe/Berlin):

- Cloudflare Worker `lemdroid-photon` (routes `p.`, `photon.`, `nu.lemdro.id`), version `1f4c2b54-c99b-46d1-a4db-e44eb3bf06d3`. Previous version, for rollback: `f8c14a68-15cb-48f6-9bce-b9cb2143c3dd` (redeploy at 100%).
- `/srv/photon` on the backend server for bare `lemdro.id`. Rollback: `sudo tar -C /srv -xzf /root/backup-explore-fix-20261120/srv-photon-before.tgz photon/index.html photon/service-worker.js`.

Files:

- `photon-v2.4.3-explore-topweek.diff`: unified diff of the deployed build (before vs after) for `index.html` (new entry and CSP sha256 for the inline boot script), `service-worker.js` (new file names and cache name `cache-1795088067009-tw1`), `nodes/5.CXr6ZXrI.js` → `5.CXr6ZXtw.js` (`||"TopDay"` → `||"TopWeek"`) and `entry/app.BN6IQGoV.js` → `app.BN6IQGtw.js` (import of the new chunk). The old files are still deployed alongside.
- `source-patch.sh`: the same change at source level, for a future build from the Photon repo (Photon has no setting for this default). Run it from the root of a Photon checkout. It will not run if upstream no longer contains `TopDay` in `src/routes/explore/+layout.ts`.

See [docs/PATCHES.md](../../../../docs/PATCHES.md) section 3.
