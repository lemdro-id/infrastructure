#!/usr/bin/env python3
"""Generate the lemdro.id Grafana dashboards (role grafana_lemdroid, files/dashboards/*.json).

Run from anywhere:  python3 ansible/scripts/gen-grafana-dashboards.py
The JSON is committed; edit this script, not the JSON (the provider has allowUiUpdates: false).
Datasource UIDs are fixed by the role's provisioning: lemdroid-influx (Flux), lemdroid-vm (VictoriaMetrics via the
read gateway), lemdroid-vl (VictoriaLogs, scrubbed store only, via the read gateway).
Metric and field names are the ones that exist on lemdroid-ovh (listed read-only 2026-11-24).
"""
import json
import os
import re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "roles", "grafana_lemdroid", "files", "dashboards")
INFLUX = {"type": "influxdb", "uid": "lemdroid-influx"}
VM = {"type": "prometheus", "uid": "lemdroid-vm"}
VL = {"type": "victoriametrics-logs-datasource", "uid": "lemdroid-vl"}
DBIP = "IP Geolocation by [DB-IP](https://db-ip.com) (DB-IP Lite City, CC BY 4.0)."


class Board:
    def __init__(self, uid, title, tags, time_from="now-7d", refresh="5m", desc=""):
        self.uid, self.title, self.tags, self.time_from, self.refresh, self.desc = uid, title, tags, time_from, refresh, desc
        self.panels, self.vars, self.y, self.next_id = [], [], 0, 1

    def row(self, title):
        self.panels.append({"type": "row", "title": title, "collapsed": False, "id": self.next_id,
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []})
        self.next_id += 1
        self.y += 1

    def add(self, panels, h):
        """Place panels left to right on one line; each panel dict has 'w'."""
        x = 0
        for p in panels:
            w = p.pop("w")
            p["id"] = self.next_id
            self.next_id += 1
            p["gridPos"] = {"x": x, "y": self.y, "w": w, "h": h}
            x += w
            self.panels.append(p)
        self.y += h

    def json(self):
        return {
            "uid": self.uid, "title": self.title, "tags": self.tags, "description": self.desc,
            "editable": False, "graphTooltip": 1, "schemaVersion": 41, "version": 1, "timezone": "browser",
            "time": {"from": self.time_from, "to": "now"}, "refresh": self.refresh, "fiscalYearStartMonth": 0,
            "links": [{"type": "dashboards", "tags": ["lemdro.id"], "asDropdown": False, "title": "lemdro.id",
                       "includeVars": False, "keepTime": True}],
            "annotations": {"list": []}, "templating": {"list": self.vars}, "panels": self.panels,
        }


def t_flux(q, ref="A"):
    return {"refId": ref, "datasource": INFLUX, "query": q}


# Vector's prometheus_remote_write only sends a lemdroid_* series when it gets an event, so rare series are sparse.
# VictoriaMetrics rate() with no earlier sample in the window divides by the span between the samples inside it
# (e.g. 3 s), which turned one 240-request burst into ~78/s for 5 min (2026-11-25 07:12 PT). increase(X[W]) / W
# divides by the window instead (MetricsQL accepts a duration as a number). Exporter-scraped metrics keep rate().
_SPARSE_RATE = re.compile(r'(?<![a-z_])rate\((lemdroid_[a-z_]+(?:\{(?:[^{}"]|"[^"]*")*\})?)\[([^\]]+)\]\)')


def sparse_rate(expr):
    return _SPARSE_RATE.sub(lambda m: f"(increase({m.group(1)}[{m.group(2)}]) / {m.group(2)})", expr)


def t_prom(expr, legend="", ref="A", instant=False, fmt="time_series"):
    t = {"refId": ref, "datasource": VM, "expr": sparse_rate(expr), "legendFormat": legend or "__auto", "range": not instant,
         "instant": instant, "format": fmt, "editorMode": "code"}
    return t


def t_vl(expr, qtype="instant", ref="A", legend="", max_lines=None):
    t = {"refId": ref, "datasource": VL, "expr": expr, "queryType": qtype, "editorMode": "code"}
    if legend:
        t["legendFormat"] = legend
    if max_lines:
        t["maxLines"] = max_lines
    return t


def ts(title, targets, w=12, unit="short", stack=False, bars=False, desc="", min0=True, overrides=None,
       legend_calcs=None, points=False):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 2 if points else 1,
              "fillOpacity": 60 if bars else (0 if points else 10), "pointSize": 6,
              "showPoints": "always" if points else "never", "spanNulls": False, "axisSoftMin": 0 if min0 else None,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}, "barAlignment": -1}
    custom = {k: v for k, v in custom.items() if v is not None}
    ds = targets[0]["datasource"]
    return {"type": "timeseries", "title": title, "description": desc, "datasource": ds, "w": w, "targets": targets,
            "fieldConfig": {"defaults": {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"}},
                            "overrides": overrides or []},
            "options": {"legend": {"displayMode": "table" if legend_calcs else "list", "placement": "bottom",
                                   "showLegend": True, "calcs": legend_calcs or []},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def stat(title, targets, w=6, unit="short", desc="", color="blue", decimals=None, graph=False, thresholds=None,
         text_mode="auto"):
    d = {"unit": unit, "color": {"mode": "thresholds" if thresholds else "fixed", "fixedColor": color}}
    if thresholds:
        d["thresholds"] = {"mode": "absolute", "steps": thresholds}
    if decimals is not None:
        d["decimals"] = decimals
    return {"type": "stat", "title": title, "description": desc, "datasource": targets[0]["datasource"], "w": w,
            "targets": targets, "fieldConfig": {"defaults": d, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "value", "graphMode": "area" if graph else "none", "textMode": text_mode,
                        "justifyMode": "auto", "orientation": "auto", "wideLayout": True}}


def table(title, targets, w=12, desc="", transformations=None, overrides=None, sort=None, unit="short"):
    p = {"type": "table", "title": title, "description": desc, "datasource": targets[0]["datasource"], "w": w,
         "targets": targets, "transformations": transformations or [],
         "fieldConfig": {"defaults": {"unit": unit, "custom": {"align": "auto", "filterable": False}},
                         "overrides": overrides or []},
         "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}}
    if sort:
        p["options"]["sortBy"] = [{"displayName": sort, "desc": True}]
    return p


def bargauge(title, targets, w=12, unit="short", desc="", transformations=None):
    return {"type": "bargauge", "title": title, "description": desc, "datasource": targets[0]["datasource"], "w": w,
            "targets": targets, "transformations": transformations or [],
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "continuous-BlPu"}, "min": 0}, "overrides": []},
            "options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                        "valueMode": "color", "namePlacement": "left", "sizing": "auto",
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True}}}


def text(md, w=24, title=""):
    return {"type": "text", "title": title, "w": w, "options": {"mode": "markdown", "content": md}}


def custom_var(name, label, options, default, multi=False, include_all=False, desc=""):
    """options: [(text, value)]"""
    cur_t = [t for t, v in options if v in (default if multi else [default])]
    cur_v = default if multi else default
    return {"type": "custom", "name": name, "label": label, "description": desc, "multi": multi,
            "includeAll": include_all, "hide": 0,
            "query": ",".join(f"{t} : {v}" for t, v in options),
            "options": [{"text": t, "value": v, "selected": (v in default) if multi else v == default}
                        for t, v in options],
            "current": {"text": cur_t if multi else cur_t[0], "value": cur_v}}


# ===================================================== 1. Interactions (Influx) ======================================
def interactions():
    b = Board("lemdroid-interactions", "lemdro.id · Interactions (who actually uses it)", ["lemdro.id", "interactions"],
              time_from="now-30d", refresh="30m",
              desc="Distinct users who commented, posted or voted (Influx lemdroid_interactions, hourly from "
                   "obs-interactions on lemdroid-ovh; counts only, no user ids). Bots and mod-removed content excluded. "
                   "Daily/weekly windows are UTC; the current window is partial until it closes.")
    b.vars = [
        custom_var("kind", "Interaction", [("any", "any"), ("comment", "comment"), ("post", "post"), ("vote", "vote")],
                   "any"),
        custom_var("where", "Communities", [("all communities", "all"), ("lemdro.id communities", "local"),
                                            ("remote communities", "remote")], "all",
                   desc="all = whole site; lemdro.id = communities hosted here; remote = communities hosted elsewhere"),
        custom_var("period", "Window (tables)", [("day", "day"), ("week", "week")], "week"),
    ]
    where = ('(if "${where}" == "all" then not exists r.community_local '
             'else r.community_local == (if "${where}" == "local" then "true" else "false"))')
    base = 'from(bucket: "lemdroid_interactions")\n  |> range(start: {start}, stop: v.timeRangeStop)\n'

    def site_series(period, fields, kind="${kind}", start="v.timeRangeStart"):
        f = " or ".join(f'r._field == "{x}"' for x in fields)
        return (base.format(start=start) +
                f'  |> filter(fn: (r) => r._measurement == "lemdroid_interactions" and r.period == "{period}" '
                f'and r.scope == "site" and {where})\n'
                f'  |> filter(fn: (r) => r.kind == "{kind}" and ({f}))\n'
                '  |> keep(columns: ["_time", "_field", "_value"])\n'
                '  |> group(columns: ["_field"])\n'
                '  |> map(fn: (r) => ({r with _field: if r._field == "users_local" then "local users" '
                'else if r._field == "users_remote" then "remote users" else "all users"}))')

    def by_kind(period, field):
        return (base.format(start="v.timeRangeStart") +
                f'  |> filter(fn: (r) => r._measurement == "lemdroid_interactions" and r.period == "{period}" '
                f'and r.scope == "site" and {where} and r._field == "{field}")\n'
                '  |> keep(columns: ["_time", "kind", "_value"])\n'
                '  |> group(columns: ["kind"])\n  |> rename(columns: {kind: "_field"})')

    def last_complete(period, field, where_expr=where):
        return (base.format(start="-35d") +
                f'  |> filter(fn: (r) => r._measurement == "lemdroid_interactions" and r.period == "{period}" '
                f'and r.scope == "site" and r.kind == "${{kind}}" and {where_expr})\n'
                f'  |> filter(fn: (r) => r._field == "{field}" or r._field == "complete")\n'
                '  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
                '  |> group()\n  |> filter(fn: (r) => r.complete == true)\n'
                f'  |> sort(columns: ["_time"])\n  |> last(column: "{field}")\n'
                f'  |> keep(columns: ["_time", "{field}"])')

    local_comms = 'r.community_local == "true"'
    all_comms = "not exists r.community_local"
    b.row("Headline: distinct active users (last COMPLETE UTC day / ISO week; kind from the variable)")
    b.add([
        stat("Local users · last full day", [t_flux(last_complete("day", "users_local", all_comms))], w=6,
             color="green", desc="lemdro.id accounts that commented/posted/voted anywhere (ignores Communities)."),
        stat("Remote users on lemdro.id communities · last full day",
             [t_flux(last_complete("day", "users_remote", local_comms))], w=6, color="purple",
             desc="People from other instances interacting in communities hosted on lemdro.id."),
        stat("Local users · last full week", [t_flux(last_complete("week", "users_local", all_comms))], w=6,
             color="green"),
        stat("Remote users on lemdro.id communities · last full week",
             [t_flux(last_complete("week", "users_remote", local_comms))], w=6, color="purple",
             desc="Remote people interacting in communities hosted on lemdro.id (ignores the Communities variable)."),
    ], 4)
    b.row("Daily (UTC days; today is partial)")
    b.add([
        ts("Daily distinct users: local vs remote (${kind}, ${where})",
           [t_flux(site_series("day", ["users_local", "users_remote"]))], w=12, bars=True,
           overrides=[{"matcher": {"id": "byName", "options": "local users"},
                       "properties": [{"id": "custom.axisPlacement", "value": "right"},
                                      {"id": "custom.drawStyle", "value": "line"},
                                      {"id": "custom.lineWidth", "value": 2},
                                      {"id": "custom.showPoints", "value": "always"},
                                      {"id": "custom.pointSize", "value": 6},
                                      {"id": "custom.fillOpacity", "value": 0},
                                      {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
                      {"matcher": {"id": "byName", "options": "remote users"},
                       "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "purple"}}]}],
           desc="Local users on the right axis (they are far fewer)."),
        ts("Daily local users by kind (${where})", [t_flux(by_kind("day", "users_local"))], w=6, points=True),
        ts("Daily remote users by kind (${where})", [t_flux(by_kind("day", "users_remote"))], w=6, points=True),
    ], 9)
    b.row("Weekly (ISO weeks, Monday 00:00 UTC; this week is partial)")
    b.add([
        ts("Weekly distinct users: local vs remote (${kind}, ${where})",
           [t_flux(site_series("week", ["users_local", "users_remote"]))], w=12, bars=True,
           overrides=[{"matcher": {"id": "byName", "options": "local users"},
                       "properties": [{"id": "custom.axisPlacement", "value": "right"},
                                      {"id": "custom.drawStyle", "value": "line"},
                                      {"id": "custom.lineWidth", "value": 2},
                                      {"id": "custom.showPoints", "value": "always"},
                                      {"id": "custom.pointSize", "value": 6},
                                      {"id": "custom.fillOpacity", "value": 0},
                                      {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
                      {"matcher": {"id": "byName", "options": "remote users"},
                       "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "purple"}}]}]),
        ts("Weekly local users by kind (${where})", [t_flux(by_kind("week", "users_local"))], w=6, points=True),
        ts("Weekly remote users by kind (${where})", [t_flux(by_kind("week", "users_remote"))], w=6, points=True),
    ], 9)

    def top_comm(filter_expr, sort_field, n=25):
        return ('data = from(bucket: "lemdroid_interactions")\n  |> range(start: -35d, stop: v.timeRangeStop)\n'
                '  |> filter(fn: (r) => r._measurement == "lemdroid_interactions" and r.period == "${period}" '
                f'and r.scope == "community" and r.kind == "${{kind}}" and {filter_expr})\n'
                'latest = data |> filter(fn: (r) => r._field == "users") |> keep(columns: ["_time"]) |> group()\n'
                '  |> max(column: "_time") |> findRecord(fn: (key) => true, idx: 0)\n'
                'data\n  |> filter(fn: (r) => r._time == latest._time and r._field != "complete")\n'
                '  |> pivot(rowKey: ["_time", "community"], columnKey: ["_field"], valueColumn: "_value")\n'
                f'  |> group()\n  |> sort(columns: ["{sort_field}"], desc: true)\n  |> limit(n: {n})\n'
                '  |> keep(columns: ["community", "users", "users_local", "users_remote"])')

    renames = [{"id": "organize", "options": {"renameByName": {"community": "Community", "users": "Distinct users",
                                                               "users_local": "Local", "users_remote": "Remote"},
                                              "indexByName": {"community": 0, "users": 1, "users_local": 2,
                                                              "users_remote": 3}}}]
    bar_cells = [{"matcher": {"id": "byName", "options": "Community"},
                  "properties": [{"id": "custom.width", "value": 210}]}]
    b.row("Communities by distinct interactors (latest ${period} window, ${kind})")
    b.add([
        table("lemdro.id communities", [t_flux(top_comm('r.community_local == "true"', "users"))], w=8,
              transformations=renames, overrides=bar_cells,
              desc="Communities hosted on lemdro.id, ranked by distinct people (local + remote) interacting."),
        table("Remote communities where lemdro.id users interact",
              [t_flux(top_comm('r.community_local == "false"', "users_local"))], w=8, transformations=renames,
              overrides=bar_cells,
              desc="Ranked by local (lemdro.id) users. Remote communities with no local users are only kept for the "
                   "top 200 by total (obs_interactions_top_remote)."),
        table("All communities (what lemdro.id sees)", [t_flux(top_comm("true", "users"))], w=8,
              transformations=renames, overrides=bar_cells),
    ], 12)
    home_q = ('data = from(bucket: "lemdroid_interactions")\n  |> range(start: -35d, stop: v.timeRangeStop)\n'
              '  |> filter(fn: (r) => r._measurement == "lemdroid_interactions" and r.period == "${period}" '
              'and r.scope == "site_home" and r.kind == "${kind}" and r._field == "users")\n'
              'latest = data |> keep(columns: ["_time"]) |> group() |> max(column: "_time") '
              '|> findRecord(fn: (key) => true, idx: 0)\n'
              'data\n  |> filter(fn: (r) => r._time == latest._time and r.home_instance != "_other")\n'
              '  |> group()\n  |> sort(columns: ["_value"], desc: true)\n  |> limit(n: 20)\n'
              '  |> keep(columns: ["home_instance", "_value"])\n  |> rename(columns: {_value: "users"})')
    b.add([
        bargauge("Where interactors come from (home instance, latest ${period})", [t_flux(home_q)], w=12,
                 transformations=[{"id": "rowsToFields", "options": {"mappings": [
                     {"fieldName": "home_instance", "handlerKey": "field.name"},
                     {"fieldName": "users", "handlerKey": "field.value"}]}}]),
        text("**How to read this**\n\n"
             "* *Local users* = lemdro.id accounts. *Remote users* = accounts on other instances whose comments, "
             "posts or votes federated here.\n"
             "* Each number is **distinct people** in the window, so days don't add up to a week.\n"
             "* *any* = did at least one of comment / post / vote.\n"
             "* Source: `obs_api.interactions()` on lemdroid-ovh (counts only), written hourly at :07 UTC to Influx "
             "bucket `lemdroid_interactions`; late federation is re-counted for 2 days.", w=12, title="Notes"),
    ], 8)
    return b


# ===================================================== 2. Health (VictoriaMetrics) ===================================
def health():
    b = Board("lemdroid-health", "lemdro.id · Health", ["lemdro.id", "health"], time_from="now-6h", refresh="1m",
              desc="lemdroid-ovh: nginx (from the access log via Vector), Postgres, host, federation. "
                   "VictoriaMetrics on lemdroid-ovh via the read-only gateway.")
    b.vars = [
        {"type": "custom", "name": "route_class", "label": "Route class", "multi": True, "includeAll": True,
         "allValue": ".*", "hide": 0, "query": "api,html,inbox,pictrs,static,wellknown,nodeinfo,feeds,health,other",
         "current": {"text": ["All"], "value": ["$__all"]}, "options": []},
    ]
    rc = 'route_class=~"$route_class"'
    b.row("Traffic (nginx, every request incl. federation)")
    b.add([
        stat("Requests/s", [t_prom(f'sum(rate(lemdroid_nginx_requests_total{{{rc}}}[5m]))', instant=True)], w=4,
             unit="reqps", decimals=1, graph=True),
        stat("5xx share (5m)", [t_prom(
            f'(sum(rate(lemdroid_nginx_requests_total{{{rc},status_class="5xx"}}[5m])) or vector(0)) / '
            f'sum(rate(lemdroid_nginx_requests_total{{{rc}}}[5m]))', instant=True)], w=4, unit="percentunit",
             decimals=2, thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.005},
                                     {"color": "red", "value": 0.02}]),
        stat("p95 latency (5m)", [t_prom(
            f'histogram_quantile(0.95, sum by (le) (rate(lemdroid_nginx_request_seconds_bucket{{{rc}}}[5m])))',
            instant=True)], w=4, unit="s", decimals=2,
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1},
                         {"color": "red", "value": 3}]),
        stat("Postgres", [t_prom('max(pg_up)', instant=True)], w=4,
             thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
        stat("Tunnel HA connections", [t_prom('max(cloudflared_tunnel_ha_connections)', instant=True)], w=4,
             thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 2},
                         {"color": "green", "value": 4}]),
        stat("Interactions job last success", [t_prom(
            'time() - max(obs_interactions_last_success_timestamp_seconds{period="day"})', instant=True)], w=4,
             unit="s", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 7200},
                                   {"color": "red", "value": 14400}]),
    ], 4)
    b.add([
        ts("Requests/s by status class", [t_prom(
            f'sum by (status_class) (rate(lemdroid_nginx_requests_total{{{rc}}}[$__rate_interval]))',
            "{{status_class}}")], w=8, unit="reqps", stack=True),
        ts("Requests/s by route class", [t_prom(
            f'sum by (route_class) (rate(lemdroid_nginx_requests_total{{{rc}}}[$__rate_interval]))',
            "{{route_class}}")], w=8, unit="reqps", stack=True),
        ts("Requests/s by client type", [t_prom(
            f'sum by (ua_class) (rate(lemdroid_nginx_requests_by_client_total{{{rc}}}[$__rate_interval]))',
            "{{ua_class}}")], w=8, unit="reqps", stack=True),
    ], 8)
    b.add([
        ts("Latency p50 / p95 / p99 (nginx request_time)", [
            t_prom(f'histogram_quantile(0.5, sum by (le) (rate(lemdroid_nginx_request_seconds_bucket{{{rc}}}'
                   '[$__rate_interval])))', "p50", "A"),
            t_prom(f'histogram_quantile(0.95, sum by (le) (rate(lemdroid_nginx_request_seconds_bucket{{{rc}}}'
                   '[$__rate_interval])))', "p95", "B"),
            t_prom(f'histogram_quantile(0.99, sum by (le) (rate(lemdroid_nginx_request_seconds_bucket{{{rc}}}'
                   '[$__rate_interval])))', "p99", "C")], w=8, unit="s"),
        ts("p95 latency by route class", [t_prom(
            f'histogram_quantile(0.95, sum by (le, route_class) (rate(lemdroid_nginx_request_seconds_bucket{{{rc}}}'
            '[$__rate_interval])))', "{{route_class}}")], w=8, unit="s"),
        ts("Slowest routes (p95, top 10)", [t_prom(
            f'topk(10, histogram_quantile(0.95, sum by (le, route) (rate(lemdroid_nginx_request_seconds_bucket{{{rc}}}'
            '[$__rate_interval]))))', "{{route}}")], w=8, unit="s"),
    ], 8)
    b.add([
        ts("5xx/s by route (top 10)", [t_prom(
            f'topk(10, sum by (route) (rate(lemdroid_nginx_requests_total{{{rc},status_class="5xx"}}'
            '[$__rate_interval])))', "{{route}}")], w=8, unit="reqps"),
        ts("nginx connections", [t_prom('sum by (__name__) ({__name__=~"nginx_connections_(active|reading|writing|waiting)"})',
                                        "{{__name__}}")], w=8),
        ts("Cloudflare tunnel: requests/s and errors/s", [
            t_prom('sum(rate(cloudflared_tunnel_total_requests[$__rate_interval]))', "requests", "A"),
            t_prom('sum(rate(cloudflared_tunnel_request_errors[$__rate_interval]))', "errors", "B")], w=8,
            unit="reqps"),
    ], 8)

    b.row("Postgres (lemmy)")
    b.add([
        ts("Connections by state (all DBs)", [
            t_prom('sum by (state) (pg_stat_activity_count)', "{{state}}", "A"),
            t_prom('max(pg_settings_max_connections)', "max_connections", "B")], w=8, stack=False,
            overrides=[{"matcher": {"id": "byName", "options": "max_connections"},
                        "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                                       {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]),
        ts("Connections by app (lemmy DB)", [t_prom(
            'sum by (usename) (pg_stat_activity_count{datname="lemmy"})', "{{usename}}")], w=8, stack=True),
        ts("Slow statements (>2 s) and lock waits per minute", [
            t_prom('sum(increase(lemdroid_pg_log_events_total{kind="slow_statement",level="LOG"}[1m]))',
                   "slow statements", "A"),
            t_prom('sum(increase(lemdroid_pg_log_events_total{kind="lock_wait"}[1m]))', "lock waits", "B"),
            t_prom('sum(increase(pg_stat_database_deadlocks{datname="lemmy"}[1m]))', "deadlocks", "C")], w=8,
            bars=True, desc="From the Postgres log (log_min_duration_statement = 2 s) via Vector; details in Logs."),
    ], 8)
    b.add([
        ts("Database size", [t_prom('pg_database_size_bytes{datname=~"lemmy|pictrs"}', "{{datname}}")], w=6,
           unit="bytes", min0=False),
        ts("Transactions/s", [
            t_prom('sum(rate(pg_stat_database_xact_commit{datname="lemmy"}[$__rate_interval]))', "commit", "A"),
            t_prom('sum(rate(pg_stat_database_xact_rollback{datname="lemmy"}[$__rate_interval]))', "rollback", "B")],
           w=6, unit="ops"),
        ts("Cache hit ratio", [t_prom(
            'sum(rate(pg_stat_database_blks_hit{datname="lemmy"}[$__rate_interval])) / '
            '(sum(rate(pg_stat_database_blks_hit{datname="lemmy"}[$__rate_interval])) + '
            'sum(rate(pg_stat_database_blks_read{datname="lemmy"}[$__rate_interval])))', "hit ratio")], w=6,
           unit="percentunit", min0=False),
        ts("Oldest transaction / blocked sessions", [
            t_prom('max by (state) (lemdroid_pg_oldest_xact_age_seconds)', "oldest xact: {{state}}", "A"),
            t_prom('max(lemdroid_pg_blocked_sessions)', "blocked sessions", "B")], w=6, unit="s",
           overrides=[{"matcher": {"id": "byName", "options": "blocked sessions"},
                       "properties": [{"id": "unit", "value": "short"},
                                      {"id": "custom.axisPlacement", "value": "right"}]}]),
    ], 8)

    b.row("Host (lemdroid-ovh)")
    b.add([
        ts("CPU busy by mode", [t_prom(
            'sum by (mode) (rate(node_cpu_seconds_total{mode!="idle"}[$__rate_interval])) / '
            'scalar(count(node_cpu_seconds_total{mode="idle"}))', "{{mode}}")], w=6, unit="percentunit", stack=True),
        ts("Memory", [
            t_prom('node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes', "used", "A"),
            t_prom('node_memory_MemAvailable_bytes', "available", "B")], w=6, unit="bytes", stack=True),
        ts("Disk used %", [t_prom(
            '1 - node_filesystem_avail_bytes{fstype=~"ext4|xfs"} / node_filesystem_size_bytes{fstype=~"ext4|xfs"}',
            "{{mountpoint}}")], w=6, unit="percentunit"),
        ts("Pressure (PSI, share of time stalled)", [
            t_prom('rate(node_pressure_cpu_waiting_seconds_total[$__rate_interval])', "cpu", "A"),
            t_prom('rate(node_pressure_memory_waiting_seconds_total[$__rate_interval])', "memory", "B"),
            t_prom('rate(node_pressure_io_waiting_seconds_total[$__rate_interval])', "io", "C")], w=6,
           unit="percentunit"),
    ], 8)
    b.add([
        ts("Network (eno1)", [
            t_prom('rate(node_network_receive_bytes_total{device="eno1"}[$__rate_interval]) * 8', "in", "A"),
            t_prom('-rate(node_network_transmit_bytes_total{device="eno1"}[$__rate_interval]) * 8', "out", "B")],
           w=8, unit="bps", min0=False),
        ts("Disk IO busy", [t_prom(
            'rate(node_disk_io_time_seconds_total{device=~"nvme.n1"}[$__rate_interval])', "{{device}}")], w=8,
           unit="percentunit"),
        ts("Load", [t_prom('node_load1', "load1", "A"), t_prom('node_load5', "load5", "B"),
                    t_prom('node_load15', "load15", "C")], w=8),
    ], 8)

    b.row("Federation")
    b.add([
        stat("Outbound instances by state", [t_prom('max by (state) (lemmy_fed_out_instances{state!="total"})',
                                                    "{{state}}", instant=True)], w=8),
        ts("Inbound: activities accepted by Lemmy / inbox POSTs by status", [
            t_prom('sum(rate(lemmy_fed_in_received_total[$__rate_interval]))', "accepted (received_activity)", "A"),
            t_prom('sum by (status_class) (rate(lemdroid_fed_in_requests_total[$__rate_interval]))',
                   "inbox {{status_class}}", "B")], w=8, unit="ops"),
        ts("Outbound: generated vs delivered progress", [
            t_prom('sum(rate(lemmy_fed_activities_generated_total[$__rate_interval]))', "generated", "A"),
            t_prom('sum(rate(lemmy_fed_out_progress_total[$__rate_interval]))', "delivered (progress)", "B")], w=8,
           unit="ops"),
    ], 8)
    b.add([
        ts("Inbound inbox POSTs by sender (top 15)", [t_prom(
            'topk(15, sum by (sig_host) (rate(lemdroid_fed_in_requests_total[$__rate_interval])))',
            "{{sig_host}}")], w=8, unit="reqps"),
        ts("Inbox p95 latency", [t_prom(
            'histogram_quantile(0.95, sum by (le) (rate(lemdroid_fed_in_request_seconds_bucket[$__rate_interval])))',
            "p95")], w=8, unit="s"),
        table("Outbound lag: major instances (activities behind)", [t_prom(
            'topk(15, max by (exported_instance) (lemmy_fed_out_lag_activities{major="true"}))', instant=True,
            fmt="table")], w=8, sort="Value",
              transformations=[{"id": "merge", "options": {}},
                               {"id": "organize", "options": {"excludeByName": {"Time": True},
                                                              "renameByName": {"exported_instance": "Instance",
                                                                               "Value": "Lag (activities)"}}}]),
    ], 8)
    return b


# ===================================================== 3. Logs (VictoriaLogs, scrubbed store) =========================
ERRORS = ('(source:nginx status:>=500) or (source:postgres level:in(ERROR, FATAL, PANIC)) '
          'or (source:journald priority:<=3)')


def logs():
    b = Board("lemdroid-logs", "lemdro.id · Error logs (scrubbed)", ["lemdro.id", "logs"], time_from="now-24h",
              refresh="1m",
              desc="VictoriaLogs main store on lemdroid-ovh (IP-free: client_net /24 or /48, redacted paths and "
                   "queries, scrubbed SQL). The vl-ip store (full IPs) is not reachable from Grafana.")
    b.vars = [{"type": "custom", "name": "source", "label": "Source", "multi": True, "includeAll": True,
               "allValue": "*", "hide": 0, "query": "nginx,postgres,journald",
               "current": {"text": ["All"], "value": ["$__all"]}, "options": []}]
    flt = f'source:in(${{source:csv}}) ({ERRORS})'
    flt_all = f'({ERRORS})'
    b.row("Errors")
    b.add([
        ts("Errors per minute by source", [t_vl(f'{flt_all} | stats by (source) count() errors', "statsRange",
                                                legend="{{source}}")], w=12, bars=True, stack=True,
           desc="nginx = 5xx responses; postgres = ERROR/FATAL/PANIC lines; journald = priority err or worse "
                "(cloudflared, docker, containerd, postgresql, telegraf, kernel)."),
        table("nginx 5xx by route and status", [t_vl(
            'source:nginx status:>=500 | stats by (route, status, upstream) count() n | sort by (n desc) | limit 20',
            "stats")], w=12, sort="n",
              transformations=vl_tx()),
    ], 9)
    b.add([
        table("Postgres errors by kind", [t_vl(
            'source:postgres level:in(ERROR, FATAL, PANIC) | stats by (level, kind) count() n | sort by (n desc)',
            "stats")], w=8, sort="n",
              transformations=vl_tx()),
        table("journald errors by unit", [t_vl(
            'source:journald priority:<=3 | stats by (unit) count() n | sort by (n desc) | limit 20', "stats")],
              w=8, sort="n",
              transformations=vl_tx()),
        ts("Slow statements and lock waits", [t_vl(
            'source:postgres kind:in(slow_statement, lock_wait) level:LOG | stats by (kind) count() n',
            "statsRange", legend="{{kind}}")], w=8, bars=True),
    ], 8)
    b.row("Error lines (newest first)")
    p = {"type": "logs", "title": "Error lines", "datasource": VL, "w": 24,
         "targets": [t_vl(f'{flt} | sort by (_time desc) | limit 1000', "instant", max_lines=1000)],
         "options": {"showTime": True, "wrapLogMessage": True, "prettifyLogMessage": False, "enableLogDetails": True,
                     "sortOrder": "Descending", "dedupStrategy": "none", "showLabels": False,
                     "showCommonLabels": False}}
    b.add([p], 16)
    p2 = {"type": "logs", "title": "Slow statements (scrubbed SQL)", "datasource": VL, "w": 24,
          "targets": [t_vl('source:postgres kind:slow_statement | sort by (_time desc) | limit 200', "instant",
                           max_lines=200)],
          "options": {"showTime": True, "wrapLogMessage": True, "prettifyLogMessage": False,
                      "enableLogDetails": True, "sortOrder": "Descending", "dedupStrategy": "none"}}
    b.add([p2], 10)
    return b


# ===================================================== 4. Maps (GeoIP, VictoriaLogs + VM) ============================
def geo_layer(name, ref, size_field, color, mode, text_field=None, max_size=30):
    loc = ({"mode": "lookup", "lookup": "geo_country", "gazetteer": "public/gazetteer/countries.json"}
           if mode == "country" else {"mode": "coords", "latitude": "geo_lat", "longitude": "geo_lon"})
    style = {"color": {"fixed": color}, "opacity": 0.5,
             "size": {"field": size_field, "fixed": 5, "min": 3, "max": max_size},
             "symbol": {"fixed": "img/icons/marker/circle.svg", "mode": "fixed"},
             "symbolAlign": {"horizontal": "center", "vertical": "center"},
             "textConfig": {"fontSize": 10, "offsetX": 0, "offsetY": 0, "textAlign": "center",
                            "textBaseline": "middle"}}
    if text_field:
        style["text"] = {"field": text_field, "fixed": "", "mode": "field"}
    layer = {"type": "markers", "name": name, "config": {"showLegend": True, "style": style}, "location": loc,
             "tooltip": True}
    if ref:
        layer["filterData"] = {"id": "byRefId", "options": ref}
    return layer


def geomap(title, targets, layers, w=24, desc="", transformations=None):
    return {"type": "geomap", "title": title, "description": desc, "datasource": targets[0]["datasource"], "w": w,
            "targets": targets, "transformations": transformations or [],
            "fieldConfig": {"defaults": {"color": {"mode": "thresholds"}, "thresholds": {
                "mode": "absolute", "steps": [{"color": "blue", "value": None}]}}, "overrides": []},
            "options": {"view": {"id": "zero", "lat": 25, "lon": 0, "zoom": 1.6, "allLayers": True},
                        "controls": {"showZoom": True, "mouseWheelZoom": True, "showAttribution": True,
                                     "showScale": False, "showMeasure": False, "showDebug": False},
                        "basemap": {"type": "default", "name": "Basemap", "config": {}},
                        "layers": layers, "tooltip": {"mode": "details"}}}


def vl_tx(ref=None, numeric=(), rename=None):
    """VictoriaLogs `stats` results arrive as one series per group (labels = the `by (...)` fields, series name =
    the stats result name). Turn them into one table: labels -> columns, the value column named after the stats
    result (requests, networks, ...), frames merged into rows. ref limits the steps to one query (multi-layer maps)."""
    flt = {"filter": {"id": "byRefId", "options": ref}} if ref else {}
    tx = [{"id": "labelsToFields", "options": {"mode": "columns", "valueLabel": "__name__"}, **flt},
          {"id": "merge", "options": {}, **flt}]
    if numeric:
        tx.append({"id": "convertFieldType", "options": {"conversions": [
            {"targetField": f, "destinationType": "number"} for f in numeric], "fields": {}}, **flt})
    tx.append({"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True},
                                             "renameByName": rename or {}}, **flt})
    return tx


def maps():
    # 6h stays the default: a map is a recent-traffic view (same window as Health). The picker still widens it.
    b = Board("lemdroid-maps", "lemdro.id · Maps (visitors and federation)", ["lemdro.id", "maps"],
              time_from="now-6h", refresh="5m",
              desc="Offline GeoIP of the truncated client network (/24, /48) only, done in Vector on lemdroid-ovh "
                   "with DB-IP Lite City. City-level at best (DB centroid rounded to 0.1 deg). " + DBIP +
                   " Datacenter tagging uses DB-IP Lite ASN, CC BY 4.0, same attribution.")
    b.vars = [
        {"type": "custom", "name": "ua", "label": "Visitors", "multi": True, "includeAll": False, "hide": 0,
         "query": "browser,app,other,bot_or_tool,none",
         "current": {"text": ["browser", "app"], "value": ["browser", "app"]},
         "options": [{"text": x, "value": x, "selected": x in ("browser", "app")}
                     for x in ("browser", "app", "other", "bot_or_tool", "none")],
         "description": "User-agent class (federation servers are on the federation map, not here)."},
        # Grafana parses "text : value" on " : " (spaces), so the colon in -geo_hosting:true stays in the value.
        # Off is LogsQL "*", which matches every row. On is a negation, so a missing geo_hosting still matches.
        {"type": "custom", "name": "hide_datacenters", "label": "Hide datacenters",
         "multi": False, "includeAll": False, "hide": 0,
         "query": "on : -geo_hosting:true,off : *",
         "current": {"text": "on", "value": "-geo_hosting:true", "selected": True},
         "options": [
             {"text": "on", "value": "-geo_hosting:true", "selected": True},
             {"text": "off", "value": "*", "selected": False},
         ],
         "description": "On drops visitor rows with geo_hosting true (datacenter/cloud ASN). "
                        "A row with no geo_hosting field, logged before ASN enrichment, still shows. "
                        "Federation panels are not filtered."},
    ]
    # geo_country:* drops rows from before GeoIP (no geo fields). stats by (geo_country) otherwise keeps an
    # empty group, which Grafana legends with the query text.
    # ${hide_datacenters} is "-geo_hosting:true" or "*". Negation keeps a missing field.
    vis = 'source:nginx ${hide_datacenters} ua_class:in(${ua:csv}) -route_class:in(inbox, health) -geo_cdn:cloudflare'
    latlon = ("geo_lat", "geo_lon")
    b.row("Visitors")
    b.add([
        geomap("Visitors by country (circle size = requests)", [
            t_vl(f'{vis} geo_country:* | stats by (geo_country) count() requests, count_uniq(client_net) networks',
                 "stats")],
            [geo_layer("Countries", None, "requests", "blue", "country", max_size=40)], w=12,
            transformations=vl_tx(),
            desc="Excludes federation (inbox), health checks and Cloudflare-egress networks (WARP/Workers). "
                 "Hide datacenters (default on) also drops geo_hosting true; a row with no geo_hosting field "
                 "still shows. Tooltip shows distinct /24 (or /48) networks too. " + DBIP),
        geomap("Visitors by city (top 1000 cities)", [
            t_vl(f'{vis} geo_lat:* | stats by (geo_country, geo_city, geo_lat, geo_lon) count() requests '
                 '| sort by (requests desc) | limit 1000', "stats")],
            [geo_layer("Cities", None, "requests", "orange", "coords", max_size=18)], w=12,
            transformations=vl_tx(numeric=latlon),
            desc="Dots at the DB's city centroid rounded to 0.1 deg; networks without a city are only in the "
                 "country map. " + DBIP),
    ], 13)
    b.add([
        table("Top countries: requests and distinct /24 (or /48) networks", [
            t_vl(f'{vis} geo_country:* | stats by (geo_country) count() requests, count_uniq(client_net) networks '
                 '| sort by (requests desc) | limit 40', "stats")], w=7,
              transformations=vl_tx(rename={"geo_country": "Country", "requests": "Requests",
                                            "networks": "Networks"}),
              sort="Requests",
              desc="Networks = distinct truncated client networks (/24 IPv4, /48 IPv6): a rough 'how many places'."),
        table("Top cities", [t_vl(
            f'{vis} geo_city:* | stats by (geo_country, geo_region, geo_city) count() requests, '
            'count_uniq(client_net) networks | sort by (requests desc) | limit 50', "stats")], w=9, sort="Requests",
              transformations=vl_tx(rename={"geo_country": "Country", "geo_region": "Region", "geo_city": "City",
                                            "requests": "Requests", "networks": "Networks"})),
        ts("Requests/s by country (top 10, all nginx traffic)", [t_prom(
            'topk(10, sum by (geo_country) (rate(lemdroid_nginx_requests_by_geo_total{ua_class=~"${ua:regex}"}'
            '[$__rate_interval])))', "{{geo_country}}")], w=8, unit="reqps", stack=True,
           desc="VictoriaMetrics lemdroid_nginx_requests_by_geo_total is labeled only by geo_country and ua_class. "
                "This panel counts every request in the selected user-agent classes, including federation inbox, "
                "health checks, and Cloudflare-egress networks. Unknown lookups are country ZZ. "
                "Hide datacenters does not apply: this counter has no geo_hosting label, so datacenter "
                "networks stay in the rate."),
    ], 10)

    fed = 'source:nginx route_class:inbox'
    b.row("Federation: inbound peers placed by their server's network")
    b.add([
        geomap("Peers sending to lemdro.id (dot size = inbox POSTs)", [
            t_vl(f'{fed} -geo_cdn:cloudflare geo_lat:* | stats by (sig_host, geo_country, geo_city, geo_lat, geo_lon) '
                 'count() activities | sort by (activities desc) | limit 500', "stats", ref="A")],
            [geo_layer("Peers", None, "activities", "green", "coords", max_size=30)], w=16,
            transformations=vl_tx(numeric=latlon),
            desc="Each dot = one sending instance (HTTP-signature host) at the city of the network it sent from. "
                 "Peers whose egress is a Cloudflare range are listed as CDN on the right instead. " + DBIP),
        table("CDN-fronted senders (Cloudflare egress, not mapped)", [t_vl(
            f'{fed} geo_cdn:cloudflare | stats by (sig_host) count() activities | sort by (activities desc) '
            '| limit 50', "stats")], w=8, sort="Activities",
              transformations=vl_tx(rename={"sig_host": "Instance", "activities": "Activities"})),
    ], 14)
    b.add([
        bargauge("Inbound activity by peer country", [t_vl(
            f'{fed} -geo_cdn:cloudflare geo_country:* | stats by (geo_country) count() activities '
            '| sort by (activities desc) | limit 20', "stats", legend="{{geo_country}}")], w=12),
        table("Top senders with location", [t_vl(
            f'{fed} geo_country:* | stats by (sig_host, geo_cdn, geo_country, geo_city) count() activities '
            '| sort by (activities desc) | limit 50', "stats")], w=12, sort="Activities",
              transformations=vl_tx(rename={"sig_host": "Instance", "geo_cdn": "CDN", "geo_country": "Country",
                                            "geo_city": "City", "activities": "Activities"})),
    ], 9)
    b.add([text("Geolocation is approximate (city at best, often only country) and comes from an offline "
                 "database on lemdroid-ovh; no lookup service is ever called. " + DBIP +
                 " Datacenter tagging uses DB-IP Lite ASN, CC BY 4.0, same attribution."
                 " Basemap tiles are loaded by your browser from the Grafana default tile provider.", w=24)], 2)
    return b


def main():
    os.makedirs(OUT, exist_ok=True)
    for fn, board in (("lemdroid-interactions.json", interactions()), ("lemdroid-health.json", health()),
                      ("lemdroid-logs.json", logs()), ("lemdroid-maps.json", maps())):
        with open(os.path.join(OUT, fn), "w") as f:
            json.dump(board.json(), f, indent=2, sort_keys=False)
            f.write("\n")
        print(os.path.normpath(os.path.join(OUT, fn)), len(board.panels), "panels")


if __name__ == "__main__":
    main()
