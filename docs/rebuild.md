# Rebuilding the backend server (lemdroid-ovh)

When: the OVH box is lost, its disks are wiped, or it moves to new hardware. Everything below is the order that
works; the playbook details are in [../ansible/README.md](../ansible/README.md).

## Impact: what goes down
- **Everything served by the box is down for the whole rebuild**: the Lemmy API and federation inbox (`lemdro.id`),
  Photon on bare `lemdro.id`, `l.lemdro.id` (lemmy-ui), `old.lemdro.id` (mlmym), images (`/pictrs`), sign-ups,
  email and the AndroidNews bot. Cloudflare answers with a tunnel error (530/1033) meanwhile.
- **Still up**: `m.`, `a.`/`alexandrite.`, `p.`/`nu.`/`photon.` (Cloudflare Workers) load, but cannot log in or
  fetch anything until the API is back.
- **Duration**: OVH install ~15 min + playbook ~15 min + dump copy (~11 GiB) + `pg_restore` of `lemmy` (several hours,
  index rebuilds dominate). Plan for half a day.
- **Data loss**: everything written after the last nightly dump (05:00 UTC). Federation partly heals itself: other
  instances retry deliveries for a while, but local posts, votes, sign-ups and DMs since the dump are gone.
- **Do not** run the old and new box at the same time with Lemmy started: double federation. Same for the bot (double posts)
  and cloudflared (two connectors split traffic between the boxes).

## 1. Fresh OVH install
- OVH manager/API: reinstall `debian13_64`, hostname `lemdroid-ovh`, SSH key `ovh_lemdroid`, default layout
  (software RAID1: 1 GB `/boot`, rest `/`, 512 MB swap per disk). This wipes both disks: Cole's explicit OK only.
- Login is `debian` (sudo); root SSH is blocked by OVH. GRUB already has OVH's serial console; the playbook keeps it.

## 2. Tailscale first join
- Mint a single-use, preauthorized, non-ephemeral auth key (1 h) and put it in the vault as `vault_tailscale_authkey`.
- To keep `100.73.194.110`, delete the old `lemdroid-ovh` device and assign that IP to the new one in the admin console;
  otherwise set the new `tailscale_ip` in `ansible/group_vars/lemdroid/vars.yml` and update CT 105 (step 5).
- A fresh OVH image has public key-only SSH. Use that only to install and join Tailscale. After joining, disable
  key expiry for the new device and clear `vault_tailscale_authkey`.
- Run the playbook over `lemdroid-ovh.alpaca-lizard.ts.net` (the inventory `ansible_host`). Once the firewall role
  is applied, SSH is Tailscale-only, and OVH IPMI is the emergency way in.

## 3. Playbook, configuration only
`ansible/vault.yml` is committed ansible-vault AES256. The password is not in git; the owner keeps it in
Google Drive. `--vault-password-file <path>` works in place of `--ask-vault-pass`. Never commit the password.
```sh
cd ansible
ansible-playbook site.yml -e @vault.yml --ask-vault-pass \
  -e lemdroid_full_upgrade=true -e photon_build_archive=/path/photon-v2.4.3.tar.gz
```
Build the Photon archive first with `ansible/scripts/build-photon.sh` (any machine with Docker).
That script builds stock Photon (Explore defaults to TopDay). To keep today's TopWeek default, apply
`ansible/roles/lemdroid_patches/photon/source-patch.sh` in the Photon checkout before the build; see
[PATCHES.md](PATCHES.md) section 3.
Nothing is started: Postgres runs empty; Lemmy, pict-rs, the frontends, cloudflared, the bot cron and the local-patch crons stay off.
Reboot once if `/var/run/reboot-required` exists (new kernel), then re-run the playbook: it should report no changes.

## 4. Data restore (CT 105 dump + B2)
Follow "Restore order" in `ansible/README.md`: copy `globals.sql`, `lemmy.dump`, `pictrs.dump` from CT 105
(`/var/lib/barman/nightly-dumps/`), verify sha256, restore globals, create the databases, `pg_restore` pictrs then lemmy.
pict-rs media needs nothing: it stays in B2 bucket `lemdroid`.

## 5. Nightly dump (CT 105)
The box side is in the playbook: role `barman` (from `globals.sql`), the pg_hba line for `100.101.238.76`, Postgres
listening on the Tailscale IP. If the IP changed, update `HOST=` in `/usr/local/bin/lemmy-nightly-dump.sh` on CT 105
and run `sudo -u barman psql -h <ip> -d lemmy -Atc 'select 1'` there.

## 6. Start services, then the tunnel
```sh
ansible-playbook site.yml -e @vault.yml --ask-vault-pass -e lemdroid_start_services=true
```
This starts pict-rs, Lemmy (only with a restored database), the frontends and `cloudflared-lemdroid`, and installs
the bot cron and the local-patch crons (now() reapply and stale active-count zeroing; see [PATCHES.md](PATCHES.md)).
Cloudflare needs no change: DNS for `lemdro.id`, `l.` and `old.` already points at the tunnel
`lemdroid-ovh`, and the tunnel's ingress lives in Cloudflare. As soon as the new connector registers, traffic flows.
Only if the tunnel itself was deleted: create a new one, update its ingress and the three CNAMEs, and put the new
token in the vault.

## 7. Verify
- `curl -s https://lemdro.id/api/v3/site | jq .site_view.site.name`, nodeinfo, a post page, an image under `/pictrs`.
- `l.` and `old.` show the Cloudflare challenge to curl (expected).
- `systemctl --failed` empty; `docker ps` shows 5 containers; `nft list ruleset` has `inet filter` plus Docker/Tailscale tables.
- Next 05:00 UTC: the CT 105 dump of lemmy + pictrs + globals succeeds.
