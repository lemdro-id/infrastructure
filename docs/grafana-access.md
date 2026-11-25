# Grafana (CT 102) access to lemdro.id metrics and logs (obs plan P2)

Grafana runs on CT 102 grafana-influx (home Proxmox, Grafana 13.3, InfluxDB 2.9). VictoriaMetrics (VM, `127.0.0.1:8428`)
and VictoriaLogs (VL, scrubbed store `127.0.0.1:9428`) run on lemdroid-ovh and stay on loopback. The vl-ip store
(`127.0.0.1:9429`, full client IPs) is never reachable from Grafana in any option below.

Interactions data needs no new path: obs-interactions already writes to Influx bucket `lemdroid_interactions` on CT 102,
so that dashboard only needs a read token on CT 102.

## Options

| | (a) Read gateway on the tailnet (chosen) | (b) Push to CT 102 | (c) SSH tunnel from CT 102 |
|---|---|---|---|
| What | `obs-vmauth` (VictoriaMetrics vmauth, uid obs) on the OVH **Tailscale IP** `:8427`, read-only path allowlist, one bearer token per datasource; nft `obs_guard` drops `:8427` from everyone except CT 102's tailnet IP | vmagent `remote_write` (metrics) and a Vector/VL sink (logs) from OVH into new VM/VL on CT 102 | CT 102 keeps an `ssh -L` to OVH; Grafana talks to `127.0.0.1` on CT 102 |
| Data leaves OVH | Only query results Grafana asks for | Full copy of metrics **and scrubbed logs** | Only query results |
| Writes possible from CT 102 | No (no write/import/delete/export/admin/vmui routes; tested) | n/a (CT 102 holds a writable copy) | Yes, unless vmauth is also used (VM/VL have no auth) |
| New credential | 2 random tokens in vault | VM/VL creds on CT 102 | A long-lived SSH key to OVH stored on CT 102, with a login able to reach loopback as uid obs (VL guard) |
| CT 102 load | None extra | Second VM + VL on a 2.3 GB-RAM / 26 GB-disk CT | autossh unit |
| Change on CT 102 | Grafana only | New services, storage | New unit + key |
| Blast radius if CT 102 is compromised | Read-only queries on 2 stores, rate-limited | Full copy already there | Shell-level SSH foothold on OVH |

**Recommendation: (a).** It keeps VM/VL on loopback, binds nothing public (Tailscale IP only; `tailscale_ip` is not
routable from the internet), gives CT 102 no write path and no shell on OVH, adds no storage on CT 102, and is one
obs-* unit that can be turned off with one variable. (b) duplicates the logs off the box and costs CT 102 memory and
disk. (c) puts an OVH SSH credential on CT 102. Fallback if Cole wants zero tailnet listeners: (c) to a loopback-only
obs-vmauth (same allowlist), with a dedicated no-shell tunnel user.

## How (a) is built (role `obs`, `obs_grafana_access_enabled`, default **false**)

- `obs-vmauth` (vmutils v1.157.0, sha256 pinned) in `obs.slice`, `MemoryMax=64M`, runs as uid `obs`,
  `After=`/`Wants=tailscaled.service`, `BindsTo=obs-nft-guard`
  (never listens without the source pin). Listens on `tailscale_ip:8427`; its own `/metrics`, `/flags`, `/debug/pprof`
  are on `127.0.0.1:8426` only (scraped by VM).
- `/etc/obs/vmauth.yml` (0640 root:obs, `no_log`): user `grafana-vm` → VM read paths (`/api/v1/query`, `query_range`,
  `series`, `labels`, `label/*/values`, `metadata`, `status/buildinfo`, `query_exemplars`); user `grafana-vl` → VL
  `/select/logsql/{query,hits,stats_query,stats_query_range,field_names,field_values,stream_field_names,stream_field_values,streams,stream_ids,facets}`
  on `:9428` only. No `unauthorized_user`: no token = 401. Concurrency 16 total; 8 for VM, 4 for VL.
- nft `table inet obs_guard` gains `chain input` (priority filter - 10, before `table inet filter`): `tcp dport 8427`
  dropped unless `ip saddr == telegraf_influx_ip` (CT 102, `100.86.226.112`); all IPv6 to 8427 dropped. Applies to
  every interface, so local processes and host-network containers can't use the gateway either.
- The P1 listener gate now allows exactly one non-loopback bind: vmauth on `tailscale_ip:8427`. Anything else still
  stops and disables the obs units.
- Tested (see `validation-vmauth.txt` in the plan folder): reads 200; no token 401; writes/import/export/delete/
  snapshot/vmui/tail/insert/traversal/cross-token 400; `/metrics` and friends on the proxy port 401/400; internal 200.

## Grafana side (role `grafana_lemdroid`, playbook `ansible/grafana.yml`, group `grafana_home`)

- Datasources (file-provisioned, `editable: false`, tokens in `secureJsonData` from vault): `lemdroid-influx`
  (Flux, `127.0.0.1:8086`, read token for `lemdroid_interactions`), `lemdroid-vm` (Prometheus type → gateway),
  `lemdroid-vl` (VictoriaLogs plugin 0.34.0 → gateway). VM/VL datasources and their dashboards are only installed
  when both gateway tokens are set.
- Dashboards (folder `lemdro.id`, `allowUiUpdates: false`): Interactions, Health, Error logs, Maps.
- Access, by owner decision: **any logged-in Grafana user** may view the lemdro.id dashboards. The play sets
  folder permission View (`1`) on the Viewer and Editor org roles. Organization admins always have access.
  There is no per-login allowlist. Anonymous access stays off, so a login is required. Sign-up, org creation,
  public dashboards, local snapshots (`GF_SNAPSHOTS_ENABLED=false`; a snapshot URL is viewable without login),
  external snapshots, and Gravatar stay off (systemd drop-in; grafana.ini untouched).

### Exposure: grafana.corvettecole.com is LAN/tailnet only

`grafana.corvettecole.com` is not publicly reachable: Nginx Proxy Manager's local access list on that proxy host
answers 403 to requests from the internet (checked from an external fetcher, 2026-11-24). An earlier note here said
it was public; those checks came in over the tailnet, which the access list treats as local. No NPM change is needed.
Anonymous access stays off regardless, so a Grafana login is still required.

## Enable record (2026-11-24, Cole's OK)

1. **Tailscale ACL**: explicit grant `100.86.226.112` (CT 102) -> `100.73.194.110` (lemdroid-ovh) `tcp:8427`, added
   above the existing allow-all grant (nothing else changed). nft `obs_guard` is what actually limits `:8427` to
   CT 102 while the allow-all grant exists.
2. Vault: `vault_obs_grafana_vm_token`, `vault_obs_grafana_vl_token` (two different `openssl rand -hex 32`),
   `vault_grafana_influx_read_token` (Influx: read on `lemdroid_interactions` only). Still open:
   `vault_grafana_admin_token` (Grafana service account, Admin; needs a Grafana admin login). Without it the play
   skips the API checks and the folder permission step, and the folder keeps Grafana's defaults (Viewer: view,
   Editor: edit; provisioned dashboards can't be saved from the UI either way).
3. Ansible SSH to CT 102 is still not set up; the Grafana role was applied by hand (same files, modes, plugin pin).
4. `obs_grafana_access_enabled: true` and `obs_geoip_enabled: true` in `group_vars/lemdroid/vars.yml`.

## Outbound from lemdroid-ovh (only when `obs_geoip_enabled`)

`obs-geoip-refresh` does two kinds of fetch, and sends no visitor data:

1. The monthly DB-IP City Lite file from `download.db-ip.com`.
2. `https://www.cloudflare.com/ips-v4` and `https://www.cloudflare.com/ips-v6`, compared with the vendored list.
   A difference only sets `obs_geoip_cf_ranges_drift`; it does not change the ranges Vector uses.

## Impact: what goes down

- lemdroid-ovh (`--tags obs`): **obs-vector restarts once even when both `obs_grafana_access_enabled` and
  `obs_geoip_enabled` are false.** The unit's MemoryMax moves from 192M to 256M (live cgroup was about 185M of
  192M), and the role installs `nginx-out.toml`. The same run **downloads and unpacks vmutils** (sha256-pinned);
  it is in `obs_binaries` unconditionally. The obs-vmauth unit is not installed while the gateway flag is false.
  Journald lines during the few-second restart are not collected (journald source starts at "now"); nginx/Postgres
  file sources resume from checkpoints. `systemctl daemon-reload`; nft `obs_guard` table reloaded (own table only);
  obs-victoriametrics reloaded (scrape config). With the gateway flag on, obs-vmauth starts (`After=` and
  `Wants=tailscaled.service`). `obs.slice` MemoryHigh/MemoryMax is 1344M/1600M with GeoIP off (was 1280M/1536M,
  so the unit caps, including obs-vmauth 64M, still fit under MemoryHigh) and 1664M/1920M with GeoIP on (vector
  512M). Nothing outside obs-* restarts; Lemmy, nginx, Postgres, pict-rs, cloudflared untouched;
  `lemdroid_start_services` stays false; no `postgres_allow_restart`.
- CT 102: grafana-server restarts (a few seconds of Grafana downtime). Influx, Telegraf untouched.

## Undo

- Gateway: `obs_grafana_access_enabled: false` + `--tags obs` → obs-vmauth stopped/disabled, unit + `vmauth.yml`
  removed, nft input chain gone, gate back to loopback-only. Or immediately on the box:
  `systemctl disable --now obs-vmauth`.
- Grafana: remove `/etc/grafana/provisioning/{datasources,dashboards}/lemdroid.yaml`,
  `/var/lib/grafana/dashboards/lemdroid`, `/etc/systemd/system/grafana-server.service.d/10-lemdroid.conf`,
  `grafana-cli plugins remove victoriametrics-logs-datasource`, `systemctl daemon-reload && systemctl restart grafana-server`.
- Revoke: rotate the two gateway tokens in vault (old ones stop working on the next `--tags obs`), delete the Influx
  read token and the Grafana service account.
