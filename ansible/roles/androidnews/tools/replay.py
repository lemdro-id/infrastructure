#!/usr/bin/env python3
"""Replay / simulation for AndroidNews v2. Never posts.

Simulates v2 polling every N minutes over the last H hours using the feed
items available right now (in published order), dedupes against the HUMAN
posts that existed on !android at each simulated moment, and compares with
what v1 actually posted (from the live server poster.log).

Usage: python3 replay.py --hours 48 --poll 15 --feed-cache feeds-live [--offline] [--embed]
Writes replay-data.json and prints a markdown report to stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import poster as P

HERE = Path(__file__).resolve().parent


def v1_posts_from_log(path: Path, start: datetime, end: datetime) -> list[tuple[datetime, str]]:
    out = []
    if not path.exists():
        return out
    txt = path.read_text(encoding="utf-8", errors="replace")
    for run in re.split(r"^--- run start ", txt, flags=re.M)[1:]:
        ts = P.parse_dt(run.split("\n", 1)[0].strip())
        for m in re.finditer(r"^Posted to !\S+: (.*)$", run, re.M):
            if ts and start <= ts <= end:
                out.append((ts, m.group(1).strip()))
    return out


def v1_cap_skips(path: Path) -> set[str]:
    txt = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return {P.normalize_url(m.group(1)) for m in re.finditer(r"daily cap reached[^\n]*\n\s+(https?://\S+)", txt)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--hours", type=float, default=48)
    ap.add_argument("--poll", type=float, default=15)
    ap.add_argument("--feed-cache", default=str(HERE / "feeds-live"))
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--log", default=str(HERE.parent / "server-snapshot" / "poster.log"))
    ap.add_argument("--lemmy-ua", default="MistakeNot-modtools/1.0")
    ap.add_argument("--embed", action="store_true", help="also cluster with a local embedding model (fastembed)")
    ap.add_argument("--embed-threshold", type=float, default=0.84)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    real_now = datetime.now(timezone.utc)
    items, health = P.collect_items(cfg, real_now, Path(args.feed_cache), args.offline)
    sim = P.prepare(items, cfg)
    lemmy = P.Lemmy(cfg["api_base"], args.lemmy_ua)
    raw = lemmy.recent_posts(cfg.get("community") or "android", args.hours + 72, max_pages=8)
    human = [e for e in raw if ((e.get("creator") or {}).get("name") or "") != (cfg.get("username") or "AndroidNews")]
    human_recs = P.lemmy_post_records(human)

    end = real_now.replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % int(args.poll))
    start = end - timedelta(hours=args.hours)
    state = {"posted": []}
    timeline = []
    human_skips: dict = {}
    t = start
    polls = 0
    while t <= end:
        polls += 1
        recs = [r for r in human_recs if P.parse_dt(r["when"]) <= t]
        P.prune_state(state, t, float(cfg["schedule"]["dedupe_hours"]))
        to_post, clusters = P.decide(items, cfg, state, recs, t, sim, resolve_primary=True)
        queued = [c for c in clusters if c.skip and c.skip.startswith("queued")]
        for c in clusters:
            if c.skip and "on !android" in c.skip and c.score >= float(cfg["scoring"]["post_min_score"]):
                key = min(i.norm_url for i in c.items)
                human_skips.setdefault(key, (t, c.score, c.items[0].title, c.skip))
        for cl in to_post:
            rec = P.record_from_cluster(cl, t)
            state["posted"].append(rec)
            timeline.append({
                "at": t, "cluster": cl, "big": cl.big, "score": cl.score, "title": cl.post_title, "url": cl.post_url,
                "outlets": cl.outlets, "official": cl.official,
                # lag clock: first news-outlet article, or the official post if it is alone
                "first": min((i.published for i in cl.items if not i.official), default=cl.first_published),
                "why": "; ".join(cl.breakdown), "decision": cl.decision, "queue": len(queued),
                "items": [(i.source_id, i.title, i.published) for i in sorted(cl.items, key=lambda x: x.published)],
            })
        t += timedelta(minutes=args.poll)

    # Final clustering over the whole window, for merge/split review.
    win_items = [i for i in items if i.published and start - timedelta(hours=6) <= i.published <= end
                 and i.title and i.norm_url]
    final = P.cluster_items(win_items, sim, cfg["clustering"])
    for cl in final:
        P.score_cluster(cl, cfg, end)

    v1 = v1_posts_from_log(Path(args.log), start, end + timedelta(minutes=30))
    capskips = v1_cap_skips(Path(args.log))

    out = []
    w = out.append
    w(f"Window: {P.fmt2(start)} → {P.fmt2(end)}  ({args.hours:g}h, poll every {args.poll:g} min, {polls} polls)\n")
    w("### Feed coverage in this snapshot\n")
    w("| feed | status | items | oldest item | newest item |\n|---|---|---|---|---|")
    by_src = defaultdict(list)
    for i in items:
        if i.published:
            by_src[i.source_id].append(i.published)
    for h in health:
        ds = sorted(by_src.get(h["id"], []))
        w(f"| {h['id']} | {h['status']} | {h['items']} | {P.fmt(ds[0]) if ds else '-'} | {P.fmt(ds[-1]) if ds else '-'} |")
    w("")
    w(f"### v2 would post ({len(timeline)})\n")
    w("| # | posted (PT / Berlin) | score | type | lag after first outlet report | outlets | headline (linked source) |\n|---|---|---|---|---|---|---|")
    for n, e in enumerate(timeline, 1):
        lag = int((e["at"] - e["first"]).total_seconds() // 60)
        typ = "**BIG**" if e["big"] else "ordinary"
        dom = re.sub(r"^https?://(www\.)?", "", e["url"]).split("/")[0]
        w(f"| {n} | {P.fmt2(e['at'])} | {e['score']:g} | {typ} | {lag // 60}h{lag % 60:02d}m | "
          f"{len(e['outlets'])}{' +official' if e['official'] else ''} | {e['title'].replace('|', '/')} ({dom}) |")
    w("")
    w("Score breakdowns:\n")
    for n, e in enumerate(timeline, 1):
        w(f"{n}. {e['why']} — {e['decision']}; queue behind it: {e['queue']}")
    w("")
    w(f"### v1 actually posted in the same window ({len(v1)}, from server poster.log)\n")
    w("| posted (PT / Berlin) | headline |\n|---|---|")
    for ts, title in v1:
        w(f"| {P.fmt2(ts)} | {title.replace('|', '/')} |")
    w("")
    # Hour-of-day histogram (PT)
    hv2 = Counter(e["at"].astimezone(P.PT).hour for e in timeline)
    hv1 = Counter(ts.astimezone(P.PT).hour for ts, _ in v1)
    w("### Posts by hour of day (PT)\n")
    w("| hour PT | " + " | ".join(f"{h:02d}" for h in range(24)) + " |")
    w("|---|" + "---|" * 24)
    w("| v1 | " + " | ".join(str(hv1.get(h, "")) for h in range(24)) + " |")
    w("| v2 | " + " | ".join(str(hv2.get(h, "")) for h in range(24)) + " |")
    w("")
    v1_titles = {P.tokens and t for _, t in v1}
    overlap = [e for e in timeline if e["title"] in v1_titles or any(P.normalize_url(e["url"]) == u for u in [])]
    capped = [e for e in timeline if P.normalize_url(e["url"]) in capskips]
    w(f"Overlap: {len(overlap)} of v2's posts were also posted by v1 (same headline); "
      f"{len(capped)} of v2's posts were items v1 saw but skipped with 'daily cap reached'.\n")

    w(f"### Stories v2 held back because a human had already posted them ({len(human_skips)})\n")
    for key, (ts, sc, title, why) in sorted(human_skips.items(), key=lambda kv: kv[1][0]):
        w(f"- {P.fmt2(ts)} score {sc:g}: {title} — {why}")
    w("")
    # Clusters
    multi = [c for c in final if len({i.norm_url for i in c.items}) > 1]
    w(f"### Clusters formed over the window ({len(final)} clusters, {len(multi)} with 2+ articles)\n")
    for cl in sorted(multi, key=lambda c: (-len(c.outlets), -c.score)):
        w(f"- **{cl.cid}** score {cl.score:g}{' BIG' if cl.big else ''}, {len(cl.outlets)} outlet(s)"
          f"{' +official' if cl.official else ''}: " + "; ".join(cl.breakdown))
        for i in sorted(cl.items, key=lambda x: x.published):
            j = i.flags.get("_joined", "seed")
            w(f"  - {P.fmt(i.published)} `{i.source_id}` {i.title}  _(join: {j})_")
    w("")

    if args.embed:
        try:
            from fastembed import TextEmbedding
            import numpy as np
            uniq = list({i.norm_url: i for i in win_items}.values())
            uniq.sort(key=lambda i: i.published)
            model = TextEmbedding("BAAI/bge-small-en-v1.5")
            vecs = np.array(list(model.embed([i.title for i in uniq])))
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            idx = {id(i): n for n, i in enumerate(uniq)}
            # same greedy algorithm and 6h window, cosine instead of layered score
            ecl: list[list[int]] = []
            win = timedelta(hours=float(cfg["clustering"]["window_hours"]))
            for n, it in enumerate(uniq):
                best, bs = None, 0.0
                for k, cl in enumerate(ecl):
                    for m in cl:
                        if abs(uniq[m].published - it.published) > win:
                            continue
                        s = float(vecs[n] @ vecs[m])
                        if s > bs:
                            best, bs = k, s
                if best is not None and bs >= args.embed_threshold:
                    ecl[best].append(n)
                else:
                    ecl.append([n])
            lab_e = {}
            for k, cl in enumerate(ecl):
                for n in cl:
                    lab_e[n] = k
            lab_v = {}
            for k, cl in enumerate(final):
                for i in cl.items:
                    if id(i) in idx:
                        lab_v[idx[id(i)]] = k
                    else:  # duplicate url object
                        for n, u in enumerate(uniq):
                            if u.norm_url == i.norm_url:
                                lab_v[n] = k
            pairs_v = {(a, b) for a in range(len(uniq)) for b in range(a + 1, len(uniq)) if lab_v.get(a) == lab_v.get(b)}
            pairs_e = {(a, b) for a in range(len(uniq)) for b in range(a + 1, len(uniq)) if lab_e[a] == lab_e[b]}
            both = pairs_v & pairs_e
            w(f"### Side-by-side: local embedding model (bge-small-en-v1.5, cosine ≥ {args.embed_threshold}, same 6h greedy)\n")
            w(f"Unique articles: {len(uniq)}. Same-story pairs: layered={len(pairs_v)}, embedding={len(pairs_e)}, "
              f"both={len(both)}. Embedding multi-article clusters: {sum(1 for c in ecl if len(c) > 1)}.\n")
            w("Pairs only the embedding model merged (first 25):\n")
            for a, b in sorted(pairs_e - pairs_v, key=lambda p: -float(vecs[p[0]] @ vecs[p[1]]))[:25]:
                w(f"- {float(vecs[a] @ vecs[b]):.2f} `{uniq[a].source_id}` {uniq[a].title}  ⟷  `{uniq[b].source_id}` {uniq[b].title}")
            w("\nPairs only the layered matcher merged (first 25):\n")
            for a, b in sorted(pairs_v - pairs_e, key=lambda p: -float(vecs[p[0]] @ vecs[p[1]]))[:25]:
                s, why = sim.score(uniq[a], uniq[b])
                w(f"- emb {float(vecs[a] @ vecs[b]):.2f} / layered {s:.2f} ({why}) `{uniq[a].source_id}` {uniq[a].title}  ⟷  `{uniq[b].source_id}` {uniq[b].title}")
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"(embedding comparison skipped: {exc})\n")

    print("\n".join(out))
    json.dump([{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in e.items() if k not in ("cluster", "items")}
               for e in timeline], open(HERE / "replay-data.json", "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
