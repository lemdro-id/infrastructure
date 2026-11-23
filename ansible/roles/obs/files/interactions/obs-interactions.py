#!/usr/bin/python3
"""lemdro.id interactions rollup (obs P1).

Calls obs_api.interactions(from, to) as the read-only Postgres role `obs` (peer auth over the unix socket). That
SECURITY DEFINER function returns COUNTS ONLY (distinct users who commented / voted / posted / any, per community
and per home instance); no person id or per-user row ever reaches this process.

Writes InfluxDB line protocol, timestamped at the UTC window start, to bucket lemdroid_interactions on CT 102
(each run deletes the window's points and writes the new set, so partial days/weeks converge to the final value and
a top-N membership change can never leave a stale tag set behind). Job health goes
to the node_exporter textfile dir -> VictoriaMetrics. Stdlib only (psql does the database part).

Schedule (systemd timer, hourly at :07 UTC):
  every run          today (partial)
  hours 00-01 UTC    + yesterday and the day before (late federation), + the current ISO week
  00, 06, 12, 18 UTC + the current ISO week (week-to-date)
  Mon/Tue 00-01 UTC  + the previous ISO week (final)
Failures: a window whose query, delete or write (after one retry) fails is kept in STATE_FILE and redone first on
the next run (timer or manual). Health metrics per period are the WORST window of the run, so a later success in the
same run can't hide a failure; obs_interactions_failed_windows{period} counts what is still pending.
Locking: one run at a time (flock on STATE_DIR/lock, wait up to 10 min), so a manual backfill and the timer never
interleave their delete/write pairs.
Manual:   obs-interactions --window day:2026-11-22 [--window week:2026-11-16] [--dry-run]
"""
import argparse
import csv
import datetime as dt
import fcntl
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
TEXTFILE = os.environ.get("OBS_TEXTFILE", "/var/lib/obs/textfile/obs_interactions.prom")
STATE_DIR = os.environ.get("OBS_INTERACTIONS_STATE_DIR", "/var/lib/obs/interactions")
STATE_FILE = os.path.join(STATE_DIR, "failed-windows.json")   # windows whose last write failed; redone first
LOCK_FILE = os.path.join(STATE_DIR, "lock")                    # one run at a time (timer vs manual)
LOCK_WAIT_S = int(os.environ.get("OBS_INTERACTIONS_LOCK_WAIT", "600"))
MAX_FAILED = 100
WRITE_RETRY_DELAY_S = 5
INFLUX_URL = os.environ.get("OBS_INFLUX_URL", "")
INFLUX_ORG = os.environ.get("OBS_INFLUX_ORG", "home")
INFLUX_BUCKET = os.environ.get("OBS_INFLUX_BUCKET", "lemdroid_interactions")
TOP_HOME = int(os.environ.get("OBS_INTERACTIONS_TOP_HOME", "25"))
TOP_SITE_HOME = int(os.environ.get("OBS_INTERACTIONS_TOP_SITE_HOME", "50"))
TOP_REMOTE = int(os.environ.get("OBS_INTERACTIONS_TOP_REMOTE", "200"))


def day_start(d):
    return dt.datetime(d.year, d.month, d.day, tzinfo=UTC)


def windows_for(now):
    today = day_start(now)
    monday = today - dt.timedelta(days=today.weekday())
    w = [("day", today)]
    if now.hour < 2:
        w += [("day", today - dt.timedelta(days=1)), ("day", today - dt.timedelta(days=2))]
    if now.hour < 2 or now.hour in (6, 12, 18):
        w.append(("week", monday))
    if now.hour < 2 and today.weekday() in (0, 1):
        w.append(("week", monday - dt.timedelta(days=7)))
    return w


def parse_window(s):
    kind, _, date = s.partition(":")
    start = day_start(dt.date.fromisoformat(date))
    if kind == "week" and start.weekday() != 0:
        raise SystemExit(f"week windows start on a Monday: {s}")
    if kind not in ("day", "week"):
        raise SystemExit(f"bad window {s}")
    return (kind, start)


SQL = """SET statement_timeout = '60s';
SELECT * FROM obs_api.interactions(:'w_from'::timestamptz, :'w_to'::timestamptz,
                                   :'top_home'::int, :'top_site_home'::int, :'top_remote'::int);
"""


def query(period, start):
    """Counts only. Window bounds and top-N limits go in as psql variables (:'var' is quoted by psql), never
    formatted into the SQL text."""
    end = start + dt.timedelta(days=1 if period == "day" else 7)
    args = ["psql", "-X", "-q", "--csv", "-v", "ON_ERROR_STOP=1",
            "-v", f"w_from={start.isoformat()}", "-v", f"w_to={end.isoformat()}",
            "-v", f"top_home={TOP_HOME}", "-v", f"top_site_home={TOP_SITE_HOME}", "-v", f"top_remote={TOP_REMOTE}",
            "-f", "-"]
    out = subprocess.run(
        args, input=SQL, check=True, capture_output=True, text=True,
        env={"PGHOST": "/var/run/postgresql", "PGDATABASE": "lemmy", **os.environ, "PGAPPNAME": "obs-interactions"},
    ).stdout
    return list(csv.DictReader(io.StringIO(out))), end


def esc(v):
    return str(v).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")


def to_lines(period, start, end, rows, now):
    ts = int(start.timestamp())
    complete = "true" if end <= now else "false"
    lines = []
    for r in rows:
        tags = [f"period={period}", f"scope={esc(r['scope'])}", f"kind={esc(r['kind'])}"]
        for k in ("community", "community_local", "home_instance"):
            if r.get(k) not in (None, ""):
                v = {"t": "true", "f": "false"}.get(r[k], r[k]) if k == "community_local" else r[k]
                tags.append(f"{k}={esc(v)}")
        ul, ur = int(r["users_local"]), int(r["users_remote"])
        lines.append(f"lemdroid_interactions,{','.join(tags)} users={ul + ur}i,users_local={ul}i,users_remote={ur}i,"
                     f"complete={complete} {ts}")
    return lines


def _influx(path, body, token, ctype):
    req = urllib.request.Request(f"{INFLUX_URL}{path}", data=body, method="POST",
                                 headers={"Authorization": f"Token {token}", "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"influx {path.split('?')[0]} HTTP {resp.status}")


def influx_replace(period, start, lines, token):
    """Replace the window: delete every lemdroid_interactions point of this period at the window's timestamp, then
    write the new set. Without the delete, a tag set that dropped out of a top-N since the last run (a home instance
    that fell into '_other', a remote community that left the top 200) would keep its stale value and be counted
    twice next to the new rows. Points only ever sit at window starts, so [start, start+1s) holds exactly this window.
    Influx 2 deletes need write permission on the bucket (the job's token is write-only on lemdroid_interactions).
    If the delete succeeded and the write fails, the write is retried once; if that fails too the window is empty in
    Influx until the next run redoes it (the caller records it in STATE_FILE)."""
    q = urllib.parse.urlencode({"org": INFLUX_ORG, "bucket": INFLUX_BUCKET})
    stop = start + dt.timedelta(seconds=1)
    pred = f'_measurement="lemdroid_interactions" AND period="{period}"'
    body = json.dumps({"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "stop": stop.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "predicate": pred}).encode()
    _influx(f"/api/v2/delete?{q}", body, token, "application/json")
    q = urllib.parse.urlencode({"org": INFLUX_ORG, "bucket": INFLUX_BUCKET, "precision": "s"})
    data = "\n".join(lines).encode()
    try:
        _influx(f"/api/v2/write?{q}", data, token, "text/plain; charset=utf-8")
    except Exception as e:  # one retry: the delete already happened, so don't leave the window empty on a blip
        print(f"{period} {start.date()} write failed ({e}); retrying once in {WRITE_RETRY_DELAY_S}s", file=sys.stderr)
        time.sleep(WRITE_RETRY_DELAY_S)
        _influx(f"/api/v2/write?{q}", data, token, "text/plain; charset=utf-8")


def load_failed():
    """Pending windows from earlier runs, as [(period, start)], oldest first. A corrupt file is reported, not fatal."""
    try:
        with open(STATE_FILE) as f:
            raw = json.load(f).get("failed", [])
        return [parse_window(f"{p}:{d}") for p, d in raw]
    except FileNotFoundError:
        return []
    except (ValueError, SystemExit, TypeError, AttributeError) as e:
        print(f"obs-interactions: ignoring unreadable {STATE_FILE}: {e}", file=sys.stderr)
        return []


def save_failed(wins):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"failed": [[p, s.date().isoformat()] for p, s in wins[-MAX_FAILED:]]}, f)
    os.replace(tmp, STATE_FILE)


def take_lock():
    os.makedirs(STATE_DIR, exist_ok=True)
    fd = open(LOCK_FILE, "a")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() > deadline:
                msg = f"obs-interactions: another run holds {LOCK_FILE} for > {LOCK_WAIT_S}s; giving up"
                raise SystemExit(msg) from None
            time.sleep(2)


def read_token():
    cred = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred and os.path.exists(os.path.join(cred, "influx-token")):
        tok = open(os.path.join(cred, "influx-token")).read().strip()
        return tok or None
    return None


def write_textfile(stats):
    """Merge this run's values into the existing file (a run that skips the week keeps the week's last values)."""
    merged = {}
    try:
        for line in open(TEXTFILE):
            m = re.match(r'^obs_interactions_(\w+)\{period="(\w+)"\} (\S+)$', line.strip())
            if m:
                merged[(m.group(2), m.group(1))] = m.group(3)
    except FileNotFoundError:
        pass
    merged.update(stats)
    os.makedirs(os.path.dirname(TEXTFILE), exist_ok=True)
    tmp = TEXTFILE + ".tmp"
    with open(tmp, "w") as f:
        for key in ("last_run_timestamp_seconds", "last_success_timestamp_seconds", "duration_seconds", "rows",
                    "influx_write_ok", "failed_windows"):
            f.write(f"# TYPE obs_interactions_{key} gauge\n")
            for period in ("day", "week"):
                if (period, key) in merged:
                    f.write(f'obs_interactions_{key}{{period="{period}"}} {merged[(period, key)]}\n')
    os.replace(tmp, TEXTFILE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", action="append", help="day:YYYY-MM-DD or week:YYYY-MM-DD (a Monday)")
    ap.add_argument("--dry-run", action="store_true", help="query and print a summary; write nothing")
    args = ap.parse_args()
    now = dt.datetime.now(UTC)
    token = None if args.dry_run else read_token()
    writing = bool(token and INFLUX_URL and not args.dry_run)
    if not args.dry_run and not writing:
        print("obs-interactions: no Influx token/URL configured; querying only (nothing written)", file=sys.stderr)
    lock = take_lock() if writing else None  # held until the end of main()
    pending = load_failed() if writing else []
    wins = [parse_window(w) for w in args.window] if args.window else windows_for(now)
    if not args.window:
        # earlier failures first, then this hour's windows; each window once
        wins = list(dict.fromkeys(pending + wins))
    elif pending:
        print(f"obs-interactions: {len(pending)} failed window(s) pending; the next timer run redoes them",
              file=sys.stderr)
    stats = {}
    worst = {}       # period -> {"ok": min over windows, "all_ok": bool, "rows": max, "dur": sum}
    failed_now = []
    for period, start in wins:
        t0 = time.monotonic()
        w = worst.setdefault(period, {"ok": 1, "all_ok": True, "rows": 0, "dur": 0.0})
        stats[(period, "last_run_timestamp_seconds")] = int(time.time())
        try:
            rows, end = query(period, start)
            lines = to_lines(period, start, end, rows, now)
            ok = 0
            if writing:
                influx_replace(period, start, lines, token)
                ok = 1
            dur = time.monotonic() - t0
            w["rows"] = max(w["rows"], len(rows))
            w["dur"] += dur
            if writing:
                w["ok"] = min(w["ok"], ok)
            site = {r["kind"]: (r["users_local"], r["users_remote"]) for r in rows
                    if r["scope"] == "site" and r["community_local"] == ""}
            print(f"{period} {start.date()} rows={len(rows)} {dur:.1f}s influx={'yes' if ok else 'no'} "
                  f"site(local/remote): " + " ".join(f"{k}={v[0]}/{v[1]}" for k, v in sorted(site.items())))
        except Exception as e:  # keep going with the other windows; the exit code reports the failure
            w["ok"], w["all_ok"] = 0, False
            w["dur"] += time.monotonic() - t0
            failed_now.append((period, start))
            print(f"{period} {start.date()} FAILED: {e}", file=sys.stderr)
    # health per period = the worst window of this run (a later success can't mask an earlier failure)
    for period, w in worst.items():
        stats.update({(period, "duration_seconds"): round(w["dur"], 3), (period, "rows"): w["rows"],
                      (period, "influx_write_ok"): w["ok"] if writing else 0})
        if w["all_ok"]:
            stats[(period, "last_success_timestamp_seconds")] = int(time.time())
    if writing:
        done = set(wins) - set(failed_now)
        still = [x for x in pending if x not in done] + [x for x in failed_now if x not in pending]
        save_failed(still)
        for period in ("day", "week"):
            stats[(period, "failed_windows")] = sum(1 for p, _ in still if p == period)
        if still:
            print("obs-interactions: pending failed windows: " + " ".join(f"{p}:{s.date()}" for p, s in still),
                  file=sys.stderr)
    if not args.dry_run:
        if args.window:
            # manual runs only update the pending count; the freshness/health gauges belong to the timer runs
            stats = {k: v for k, v in stats.items() if k[1] == "failed_windows"}
        if stats:
            write_textfile(stats)
    if lock:
        lock.close()
    return 1 if failed_now else 0


if __name__ == "__main__":
    sys.exit(main())
