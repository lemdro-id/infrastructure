# lemdroid-ovh as code (Ansible)

Rebuilds the lemdro.id backend server (OVH SYS-2, Debian 13) from a fresh OVH Debian 13 install.
Full procedure with impact: [../docs/rebuild.md](../docs/rebuild.md).

It manages configuration only. **Data is never managed here**: Postgres contents come from the CT 105 nightly
dump and pict-rs media already lives in Backblaze B2 (see [Restore order](#restore-order)).

Verified on 2026-11-19 with `--check --diff` against the live box: no differences except the
comment-only ones listed under [Known check-mode differences](#known-check-mode-differences).

## What it covers
| Role | On the box |
|---|---|
| `base` | hostname, UTC, base packages (incl. `cron`, `tzdata-legacy`), en_US.UTF-8 locale, sshd drop-in + `ClientAliveInterval 120`, `ip_nonlocal_bind` sysctl, SCTP blocked, LLMNR/mDNS off, unattended-upgrades (Debian + security only) and apt timers, GRUB as OVH ships it (serial console `ttyS1`) |
| `firewall` | `/etc/nftables.conf` (own `inet filter` table: SSH 22 + Tailscale UDP 41641 public, all on `tailscale0`, forward drop) and the `nftables.service` drop-in so stop/restart never flushes Docker's or Tailscale's tables |
| `tailscale` | official trixie repo, join as `lemdroid-ovh` with `--accept-dns=false` (auth key only on first join) |
| `postgres` | PGDG `trixie-pgdg`, PostgreSQL 16, en_US.UTF-8 cluster, `conf.d/10-lemdroid.conf`, pg_hba line for CT 105 (`barman`), start after tailscaled; checks roles/databases read-only |
| `docker` | Docker CE repo + packages (default daemon config) |
| `photon` | `/srv/photon` static Photon build (from `scripts/build-photon.sh`) |
| `pictrs` | `/root/pictrs` with `../pictrs/docker-compose.yml` and a templated `pictrs.env` |
| `lemmy` | `/root/lemmy` compose (Lemmy 0.19.21, host net, 127.0.0.1:8080) and templated `config.hjson` |
| `frontends` | `/root/frontends` with `../box/frontends/{docker-compose.yml,nginx.conf}` (nginx, lemmy-ui, mlmym) |
| `cloudflared` | Cloudflare apt repo, `cloudflared`, token file, `../box/frontends/cloudflared-lemdroid.service` |
| `androidnews` | user `androidnews` (uid 999 / gid 992), `/opt/android-news-bot` code + password, cron every 30 min |

Not managed (comes from the OVH installer or is data): partitioning/RAID1, netplan, cloud-init, `debian.sources`,
the `debian` user and its SSH key, exim4 (local-only default), Postgres contents, pict-rs media,
AndroidNews `state.json`/`poster.log`. Cloudflare (DNS, tunnel ingress, Workers, WAF) is a separate follow-up.

## Safety switches
- `lemdroid_start_services` (default **false**): without it the playbook installs and configures but never starts
  pict-rs, Lemmy, the frontends or cloudflared, and never installs the AndroidNews cron. Lemmy additionally refuses
  to start unless the `lemmy` database has been restored. Never run two copies of Lemmy or the bot (double
  federation, double posts).
- `lemdroid_full_upgrade` (default false): `apt full-upgrade`, fresh installs only.
- `postgres_bootstrap_roles` (default false): create roles without a dump (test VMs only).
- Handlers: Postgres restarts only if `conf.d` changes; cloudflared restarts only if the token changes (a unit-file
  change is a daemon-reload); nginx reloads gracefully.

## Secrets
All secrets are variables; names and placeholders are in [`vault.example.yml`](vault.example.yml). Keep the real
file **outside this repo** (it is public), encrypted with `ansible-vault`, and pass it with `-e @path`.
Secret-bearing tasks use `no_log` and `diff: false`, so check runs never print them.

## Usage
```sh
cd ansible
python3 -m venv .venv && .venv/bin/pip install 'ansible-core>=2.17'
.venv/bin/ansible-galaxy collection install -r requirements.yml

# Drift check against the live box (changes nothing):
.venv/bin/ansible-playbook site.yml -e @/secure/vault.yml --ask-vault-pass \
  -e lemdroid_start_services=true --check --diff

# Fresh box, configuration only (nothing starts):
.venv/bin/ansible-playbook site.yml -e @/secure/vault.yml --ask-vault-pass \
  -e lemdroid_full_upgrade=true -e photon_build_archive=/path/photon-v2.4.3.tar.gz
```
Check mode needs `python3-apt` on the target (present on the live box; the playbook installs it on a fresh box).
Ansible leaves empty `~/.ansible/tmp` directories on the target, even in check mode.

## Restore order
1. **OS + playbook** with `lemdroid_start_services=false` (see `docs/rebuild.md`). Postgres is running, empty,
   en_US.UTF-8; nothing else is started.
2. **Copy the latest verified dump from CT 105** (`/var/lib/barman/nightly-dumps/`: `globals.sql`, `lemmy.dump`,
   `pictrs.dump` + `.sha256`) to the box over Tailscale; `sha256sum -c`. `globals.sql` holds password hashes: mode
   600, never print it.
3. **Roles**: `sudo -u postgres psql -d postgres -f globals.sql` (errors for the existing `postgres` role are expected).
   This restores `lemmy`, `pictrs` and `barman` with their original passwords, which match the vault and CT 105's `.pgpass`.
4. **Databases**: re-run the playbook (it creates empty `lemmy`/`pictrs` owned by their roles, en_US.UTF-8), or
   `createdb -O lemmy -T template0 -l en_US.UTF-8 lemmy` and the same for `pictrs`.
5. **Data**: `pg_restore -d pictrs --exit-on-error pictrs.dump` (minutes), then
   `pg_restore -d lemmy -j 8 --exit-on-error lemmy.dump` (hours; rebuilds all indexes). Then `ANALYZE`.
6. **pict-rs media**: nothing to restore. It is in B2 bucket `lemdroid`; pict-rs reads it with the B2 keys from the vault.
7. **AndroidNews state** (optional): restore `state.json` if a copy exists (owner `androidnews`, mode 600).
8. **Start**: re-run with `-e lemdroid_start_services=true` (pict-rs, Lemmy, frontends, cloudflared, bot cron).
   Only once the old box is definitely down.
9. **CT 105**: if the box's Tailscale IP changed, update `HOST=` in `/usr/local/bin/lemmy-nightly-dump.sh` on CT 105
   and `tailscale_ip` here.

## Known check-mode differences
Against the live box on 2026-11-19 (4 tasks, 5 files), all comment-only, no functional change. Applying would make
the box match the repo:
- `/root/frontends/docker-compose.yml`, `/root/frontends/nginx.conf`, `/etc/systemd/system/cloudflared-lemdroid.service`:
  the repo copies (PR #28) dropped Fly-era comments and the unit's Description suffix.
- `/root/pictrs/docker-compose.yml`: same comment cleanup from the repo.
- `/etc/cron.d/android-news-bot`: a stale "DISABLED until cutover" comment replaced (the job line is identical).
