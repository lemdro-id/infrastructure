#!/usr/bin/python3
"""lemdro.id obs P2: refresh the offline GeoIP database (DB-IP "IP to City Lite", CC BY 4.0) for Vector.

Weekly (obs-geoip-refresh.timer). Stdlib only. Runs as uid obs; the only privileged step is the unit's
ExecStartPost (+), which reloads obs-vector (SIGHUP) when this run installed a new file.

  1. Pick the newest monthly release (this month, else last month). Skip the download if it is already installed.
  2. Download the .mmdb.gz (size-capped), gunzip (size-capped), check the MaxMind metadata says DBIP-City,
     then run `vector test` with the candidate (same binary and lookup shape as production).
  3. Atomic install: live -> .prev, candidate -> live; write state.json; touch .changed for the reload.
  4. Compare the vendored Cloudflare ranges (rendered by Ansible) with https://www.cloudflare.com/ips-v4|v6.
     A difference only sets obs_geoip_cf_ranges_drift=1 (the fix is a PR to obs_cloudflare_ips).
Never replaces a good database with a bad one: any failure leaves the live file untouched and exits non-zero.
Nothing here sends client data anywhere. Outbound requests are the DB-IP City Lite file from
download.db-ip.com, then https://www.cloudflare.com/ips-v4 and /ips-v6 for the CDN-range drift check.
Health -> node_exporter textfile dir -> VictoriaMetrics (obs_geoip_*).
"""
import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

GEO_DIR = os.environ.get("OBS_GEOIP_DIR", "/var/lib/obs/geoip")
LIVE = os.path.join(GEO_DIR, "dbip-city-lite.mmdb")
STATE = os.path.join(GEO_DIR, "state.json")
CHANGED = os.path.join(GEO_DIR, ".changed")
URL_TEMPLATE = os.environ.get("OBS_GEOIP_URL_TEMPLATE", "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz")
CF_LIST = os.environ.get("OBS_GEOIP_CF_LIST", "/etc/obs/geoip/cloudflare-ips.txt")
SELFTEST = os.environ.get("OBS_GEOIP_SELFTEST", "/etc/obs/geoip/selftest.toml")
VECTOR = os.environ.get("OBS_VECTOR_BIN", "/opt/obs/bin/vector")
TEXTFILE = os.environ.get("OBS_TEXTFILE", "/var/lib/obs/textfile/obs_geoip.prom")
MAX_GZ = 150 * 1024 * 1024
MAX_RAW = 400 * 1024 * 1024
MIN_RAW = 50 * 1024 * 1024
UA = "lemdroid-obs-geoip/1 (+https://lemdro.id)"


def fetch(url, limit, dest=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if dest is None:
            data = r.read(limit + 1)
            if len(data) > limit:
                raise ValueError(f"{url}: larger than {limit} bytes")
            return data
        n = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                n += len(chunk)
                if n > limit:
                    raise ValueError(f"{url}: larger than {limit} bytes")
                f.write(chunk)
    return None


def mmdb_metadata(path):
    """database_type and build_epoch from the MaxMind metadata section (last 128 KiB of the file)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 131072))
        tail = f.read()
    i = tail.rfind(b"\xab\xcd\xefMaxMind.com")
    if i < 0:
        raise ValueError("no MaxMind metadata marker")
    meta = tail[i:]
    j = meta.find(b"database_type")
    if j < 0:
        raise ValueError("no database_type in metadata")
    # value is a short UTF-8 string (control byte 0x40|len) right after the key
    ctrl = meta[j + 13]
    if ctrl >> 5 != 2:
        raise ValueError("unexpected database_type encoding")
    n = ctrl & 0x1F
    dbtype = meta[j + 14:j + 14 + n].decode("utf-8", "replace")
    return dbtype


def selftest(candidate):
    with open(SELFTEST) as f:
        cfg = f.read().replace("@CANDIDATE@", candidate)
    with tempfile.NamedTemporaryFile("w", suffix=".toml", dir=GEO_DIR, delete=False) as t:
        t.write(cfg)
        tmp = t.name
    try:
        r = subprocess.run([VECTOR, "test", tmp], capture_output=True, text=True, timeout=300,
                           env={"PATH": "/usr/bin:/bin", "VECTOR_LOG": "error"})
        if r.returncode != 0:
            raise ValueError("vector selftest failed: " + (r.stdout + r.stderr)[-800:])
    finally:
        os.unlink(tmp)


def cf_drift():
    """1 = Cloudflare's published ranges differ from the vendored list, 0 = same, -1 = check failed."""
    try:
        with open(CF_LIST) as f:
            vendored = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
        live = set()
        for u in ("https://www.cloudflare.com/ips-v4", "https://www.cloudflare.com/ips-v6"):
            live |= {ln.strip() for ln in fetch(u, 65536, timeout=30).decode().splitlines() if ln.strip()}
        if not live:
            return -1
        if live != vendored:
            print(f"cloudflare ranges drift: +{sorted(live - vendored)} -{sorted(vendored - live)}", file=sys.stderr)
            return 1
        return 0
    except Exception as e:  # noqa: BLE001 - a failed check is reported, never fatal
        print(f"cloudflare ranges check failed: {e}", file=sys.stderr)
        return -1


def write_textfile(stats):
    tmp = TEXTFILE + ".tmp"
    with open(tmp, "w") as f:
        for k, v in stats.items():
            f.write(f"# TYPE obs_geoip_{k} gauge\nobs_geoip_{k} {v}\n")
    os.replace(tmp, TEXTFILE)


def main():
    os.umask(0o027)
    state = {}
    if os.path.exists(STATE):
        try:
            with open(STATE) as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
    stats = {"last_run_timestamp_seconds": int(time.time()), "refresh_ok": 0}
    ok = False
    try:
        today = dt.datetime.now(dt.timezone.utc).date()
        first = today.replace(day=1)
        months = [first.strftime("%Y-%m"), (first - dt.timedelta(days=1)).strftime("%Y-%m")]
        if state.get("month") in months[:1] and os.path.exists(LIVE):
            print(f"db {state['month']} already installed")
            ok = True
        else:
            last_err = None
            for month in months:
                if state.get("month") == month and os.path.exists(LIVE):
                    print(f"db {month} already installed (newer month not published yet)")
                    ok = True
                    break
                url = URL_TEMPLATE.format(month=month)
                gz = os.path.join(GEO_DIR, f".dl-{month}.mmdb.gz")
                cand = os.path.join(GEO_DIR, f".candidate-{month}.mmdb")
                try:
                    fetch(url, MAX_GZ, dest=gz)
                    h = hashlib.sha256()
                    n = 0
                    with gzip.open(gz, "rb") as src, open(cand, "wb") as dst:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            n += len(chunk)
                            if n > MAX_RAW:
                                raise ValueError("uncompressed db too large")
                            h.update(chunk)
                            dst.write(chunk)
                    if n < MIN_RAW:
                        raise ValueError(f"uncompressed db too small ({n} bytes)")
                    dbtype = mmdb_metadata(cand)
                    if not dbtype.startswith("DBIP-City"):
                        raise ValueError(f"unexpected database_type {dbtype!r}")
                    selftest(cand)
                    if os.path.exists(LIVE):
                        shutil.copy2(LIVE, LIVE + ".prev")
                    os.replace(cand, LIVE)
                    os.chmod(LIVE, 0o640)
                    state = {"month": month, "sha256": h.hexdigest(), "bytes": n, "database_type": dbtype,
                             "installed_at": int(time.time()), "source": url,
                             "licence": "CC BY 4.0, IP Geolocation by DB-IP (https://db-ip.com)"}
                    with open(STATE + ".tmp", "w") as f:
                        json.dump(state, f)
                    os.replace(STATE + ".tmp", STATE)
                    open(CHANGED, "w").close()
                    print(f"installed {month} ({n} bytes, {dbtype}, sha256 {h.hexdigest()[:16]}...)")
                    ok = True
                    break
                except Exception as e:  # noqa: BLE001 - try the previous month, then fail
                    last_err = e
                    print(f"{month}: {e}", file=sys.stderr)
                finally:
                    for p in (gz, cand):
                        if os.path.exists(p):
                            os.unlink(p)
            if not ok:
                raise RuntimeError(f"no usable release: {last_err}")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {e}", file=sys.stderr)
    stats["refresh_ok"] = 1 if ok else 0
    if ok:
        stats["last_success_timestamp_seconds"] = int(time.time())
    if os.path.exists(LIVE):
        stats["db_installed_timestamp_seconds"] = int(state.get("installed_at", os.path.getmtime(LIVE)))
    stats["cf_ranges_drift"] = cf_drift()
    try:
        write_textfile(stats)
    except OSError as e:
        print(f"textfile: {e}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
