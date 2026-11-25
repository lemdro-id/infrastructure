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

- `obs-vmauth` (vmutils v1.157.0, sha256 pinned) in `obs.slice`, `MemoryMax=64M`, runs as uid `obs`, `BindsTo=obs-nft-guard`
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
- Cole-only: systemd drop-in env (grafana.ini untouched) — anonymous off, sign-up off, org creation off, public
  dashboards off, external snapshots off, Gravatar off. Folder permission set to Admin only through the API.
  OSS Grafana cannot restrict datasources per user, so org membership is the gate: the play fails if the org has
  users other than `grafana_lemdroid_allowed_logins`.

### Finding: Grafana is reachable from the internet

`grafana.corvettecole.com` answers from the public internet (Grafana 13.3.0 login page through Nginx Proxy Manager),
although the home docs describe it as LAN/tailnet-only. Anonymous access is already off. Recommended (needs Cole's
OK; NPM via its UI/API only): an NPM access list on that proxy host (LAN + tailnet ranges), or drop the public host.
Until then, the login page is the only barrier in front of the lemdro.id dashboards.

## Needs Cole's OK (none of this is done)

1. **Tailscale ACL**: allow CT 102 (grafana-influx) → lemdroid-ovh `tcp:8427` (and nothing broader). The tailnet
   currently looks permissive (OVH sees all peers); if so, no change is strictly required, but an explicit grant
   (plus tightening the default) is the recommended state.
2. Vault: `vault_obs_grafana_vm_token`, `vault_obs_grafana_vl_token` (two different `openssl rand -hex 32`),
   `vault_grafana_influx_read_token` (Influx: read on `lemdroid_interactions` only), `vault_grafana_admin_token`
   (Grafana service account, Admin).
3. Ansible SSH access to CT 102 for `grafana.yml` (not set up today), or apply the role by hand.
4. NPM access list for `grafana.corvettecole.com` (above).
5. Setting `obs_grafana_access_enabled: true` and `obs_geoip_enabled: true` in `group_vars/lemdroid`.

## Impact: what goes down

- lemdroid-ovh (`--tags obs`): obs-vector restarts once (config + new nginx-out file); journald lines during the
  few-second restart are not collected (journald source starts at "now"); nginx/Postgres file sources resume from
  checkpoints. `systemctl daemon-reload`; nft `obs_guard` table reloaded (own table only); obs-victoriametrics
  reloaded (scrape config). obs-vmauth started. Nothing outside obs-* restarts; Lemmy, nginx, Postgres, pict-rs,
  cloudflared untouched; `lemdroid_start_services` stays false; no `postgres_allow_restart`.
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
