#!/usr/bin/env python3
"""AndroidNews poster v2 for lemdro.id (!android).

What changed from v1:
  * Polls every 10-15 min (cron) and posts throughout the day instead of
    burning a calendar-day cap right after midnight PT.
  * Clusters the same story across feeds (layered matching), scores impact by
    independent-outlet coverage (owners de-duplicated), official sources and
    keywords, minus penalties for deals, listicles, opinion, rumors, etc.
  * Big stories (3+ independent outlets) post on the next poll, 24/7.
    Ordinary stories queue and drain at most one per `min_gap_minutes`,
    best-first, outside quiet hours.
  * Rolling 24h cap (not reset at midnight); big stories may overflow by N.
  * 48h dedupe by normalized URL and by story cluster, against our own state
    and against recent !android posts (so we never repost a human's post).

Posts use the original headline and link only. No generated summaries.
Default is --dry-run. Real posting needs --post and $ANDROIDNEWS_PASSWORD.
Passwords and JWTs are never printed.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import yaml
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent
PT = ZoneInfo("America/Los_Angeles")
BERLIN = ZoneInfo("Europe/Berlin")

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def local_name(tag: str) -> str:
    return tag.split("}")[-1] if tag else tag


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = dateparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "s", "src", "source",
}


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    pairs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS
    ]
    query = urllib.parse.urlencode(sorted(pairs))
    path = parsed.path.rstrip("/") or "/"
    return f"https://{host}{path}" + (f"?{query}" if query else "")


def fmt(dt: datetime | None, tz: ZoneInfo = PT) -> str:
    if dt is None:
        return "?"
    local = dt.astimezone(tz)
    return local.strftime(f"%a %m-%d %H:%M {local.tzname()}")


def fmt2(dt: datetime | None) -> str:
    """PT (bot logic) plus Berlin (Cole)."""
    if dt is None:
        return "?"
    return f"{fmt(dt, PT)} / {dt.astimezone(BERLIN).strftime('%H:%M %Z')}"


# --------------------------------------------------------------------------
# Text: tokens, entities, events
# --------------------------------------------------------------------------

# Headline filler: verbs/adjectives every outlet uses, which should not make
# two different stories look alike.
STOPWORDS = set(
    """
    a an the and or but of to for in on at by with from as is are was were be been being it its
    this that these those you your yours we our they their them he she his her i me my
    here here's heres what whats what's how why when where who which there that's
    now new just finally officially still also even more most less very really big huge
    gets get got getting will would could can may might should must has have had having do does did
    about into over after before than then up down out off all any some every no not only
    first one two three latest next major minor update updates updated report reports reportedly
    says said say confirms confirmed official announces announced launches launched launch
    rolls rolling roll out available arrives arriving comes coming brings bring adds add adding
    lets let make makes making give gives giving takes take finally soon today week weekend
    google's samsung's u gallery video exclusive breaking via vs series lineup right quietly
    """.split()
)

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+]*[a-z0-9+]|[a-z0-9]")  # hyphens split compounds


SYNONYMS: list[tuple[re.Pattern[str], str]] = []


def set_synonyms(mapping: dict[str, list[str]] | None) -> None:
    """config `synonyms`: canonical token -> phrases that mean the same story topic."""
    SYNONYMS.clear()
    for canon, phrases in (mapping or {}).items():
        for ph in phrases:
            SYNONYMS.append((re.compile(r"\b" + ph + r"\b", re.I), f" {canon} "))


def tokens(text: str) -> list[str]:
    text = html.unescape(text or "").lower().replace("\u2019", "'").replace("\u2018", "'")
    for rx, canon in SYNONYMS:
        text = rx.sub(canon, text)
    text = re.sub(r"\[[^\]]*\]|\((?:update|updated|u)[^)]*\)", " ", text)
    text = re.sub(r"'s\b", "", text)
    out = []
    for tok in TOKEN_RE.findall(text):
        tok = tok.strip(".-")
        if not tok or tok in STOPWORDS:
            continue
        out.append(stem(tok))
    return [t for t in out if t not in STOPWORDS]


def stem(tok: str) -> str:
    """Tiny, consistent suffix stripper (not pretty, just stable):
    leaks/leaked/leaking -> leak, release/released/releasing -> releas."""
    if any(ch.isdigit() for ch in tok) or len(tok) <= 3 or "-" in tok:
        return tok
    for suf in ("ies", "es", "s"):
        if tok.endswith(suf) and not tok.endswith("ss") and len(tok) - len(suf) >= 3:
            tok = tok[: -len(suf)] + ("y" if suf == "ies" else "")
            break
    if tok.endswith("ly") and len(tok) > 6:
        tok = tok[:-2]
    for suf in ("ing", "ed"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            tok = tok[: -len(suf)]
            if len(tok) > 3 and tok[-1] == tok[-2] and tok[-1] not in "aeiouls":
                tok = tok[:-1]
            break
    if tok.endswith("e") and len(tok) > 3:
        tok = tok[:-1]
    return tok


# Product-line anchors. A strong entity is an anchor plus the model words /
# numbers after it, e.g. "Galaxy Z Fold 8", "Razr Flex", "One UI 9.5",
# "Android 17 QPR2", "Pixel 11 Pro". Model codes like S26, A57, Raptor27 too.
ANCHORS = {
    "pixel", "galaxy", "android", "one ui", "wear os", "chromeos", "oneplus", "redmi", "poco", "razr", "moto",
    "nothing phone", "cmf phone", "coloros", "hyperos", "oxygenos", "magic os", "harmonyos", "xperia", "zenfone",
    "rog phone", "fairphone", "iphone", "ipad", "ios", "gemini", "tensor", "snapdragon", "dimensity", "exynos",
    "googlebook", "chromebook", "xiaomi", "vivo", "oppo", "honor", "realme", "motorola", "edge", "find",
}
MODEL_WORDS = {
    "z", "fold", "flip", "tab", "watch", "buds", "ring", "note", "edge", "ultra", "pro", "plus", "max", "mini",
    "lite", "fe", "xl", "flex", "duo", "neo", "gt", "nano", "flash", "signature", "duet", "studio", "tag", "go",
    "beta", "qpr", "auto", "tv", "xr", "active", "fit", "live", "a", "s", "x", "t",
    "fold8", "flip8", "tablet", "earbuds", "drop", "elite", "gen", "series",
}
MODEL_CODE_RE = re.compile(r"\b([a-z]{1,8}\d{1,4}[a-z]{0,3})\b")
VERSION_RE = re.compile(r"^\d+(\.\d+)?[a-z]?$|^qpr\d$|^dp\d$|^(19|20)\d\d$")


def _ent_key(words: list[str]) -> str:
    # "fold 8" == "fold8", "one ui 9.5" == "oneui9.5": canonical form drops spaces.
    return "".join(words)


def strong_entities(title: str) -> set[str]:
    text = html.unescape(title or "").replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"'s\b", "", text)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+]*", text)
    low = [w.lower().rstrip(".") for w in words]
    out: set[str] = set()
    i = 0
    while i < len(low):
        anchor = None
        if i + 1 < len(low) and f"{low[i]} {low[i+1]}" in ANCHORS:
            anchor, j = [low[i], low[i + 1]], i + 2
        elif low[i] in ANCHORS:
            anchor, j = [low[i]], i + 1
        if not anchor:
            i += 1
            continue
        tail: list[str] = []
        while j < len(low) and len(tail) < 4 and (low[j] in MODEL_WORDS or VERSION_RE.match(low[j])
                                                  or MODEL_CODE_RE.fullmatch(low[j])):
            tail.append(low[j])
            j += 1
        # trim trailing generic words ("pixel a" is fine, "galaxy series" is not)
        while tail and tail[-1] in {"series", "a", "s", "x", "t", "go", "live", "drop"} and len(tail) == 1 and \
                not anchor[0] in {"pixel", "galaxy"}:
            tail.pop()
        if tail:
            for k in range(1, len(tail) + 1):
                if k == 1 and tail[0] in {"z", "beta"}:
                    continue
                out.add(_ent_key(anchor + tail[:k]))
        i = max(j, i + 1)
    for m in MODEL_CODE_RE.finditer(" ".join(low)):
        code = m.group(1)
        if not re.fullmatch(r"(19|20)\d\d|\d+(gb|tb|mp|hz|w|mah|k|x|nm|th|nd|rd|st|m|s|h|fps)|q\d|m\d+|h\d+", code) \
                and re.search(r"[a-z]{1,}\d", code):
            out.add(code)
    return out


NAMED = [
    "google messages", "google wallet", "google play", "play store", "google photos", "google maps", "google home",
    "google tv", "google fi", "google voice", "google drive", "gmail", "youtube music", "youtube", "whatsapp",
    "telegram", "signal", "chrome", "gemini", "gemini nano", "circle to search", "find hub", "find my device",
    "android auto", "android tv", "android xr", "wear os", "pixel watch", "pixel buds", "pixel tablet", "pixel tag",
    "pixel drop", "feature drop", "now brief", "galaxy ai", "smartthings", "quick share", "rcs", "app lock",
    "security bulletin", "security patch", "play integrity", "material 3",
    "material you", "magic cue", "grapheneos", "lineageos", "f-droid", "calyxos", "epic", "openai", "chatgpt",
    "qualcomm", "mediatek", "tsmc", "verizon", "t-mobile", "at&t", "fcc", "eu", "dma", "doj", "antitrust",
    "samsung", "google", "apple", "microsoft", "amazon", "meta", "motorola", "oneplus", "xiaomi", "nothing", "honor",
    "oppo", "vivo", "huawei", "sony", "lenovo", "hmd", "fairphone", "garmin", "fitbit", "xreal", "aawireless",
    "googlebook", "chromebook", "one ui", "hyperos", "coloros", "oxygenos",
]
NAMED_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(NAMED, key=len, reverse=True)) + r")\b", re.I)
COMPANY_ENTITIES = {
    "samsung", "google", "apple", "microsoft", "amazon", "meta", "motorola", "oneplus", "xiaomi", "nothing", "honor",
    "oppo", "vivo", "huawei", "sony", "lenovo", "hmd", "fairphone", "garmin", "fitbit", "qualcomm", "mediatek", "tsmc",
}
NUMBER_RE = re.compile(r"(\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*\s?(?:mah|gb|tb|mp|hz|w|nits|%)|\b(?:19|20)\d\d\b)", re.I)


def norm_entity(text: str) -> str:
    t = re.sub(r"\s+", " ", text.lower()).strip()
    t = t.replace("oneui", "one ui").replace("wearos", "wear os").replace("magicos", "magic os")
    t = re.sub(r"qpr\s+(\d)", r"qpr\1", t)
    t = re.sub(r"[\s,]", "", t) if t.startswith("$") else t
    return t


def entities(title: str) -> tuple[set[str], set[str]]:
    """Return (strong, weak). Strong = product lines/models/versions.
    Weak = named apps/services/companies and notable numbers."""
    text = html.unescape(title or "").replace("\u2019", "'")
    strong = strong_entities(text)
    weak = {norm_entity(m.group(1)) for m in NAMED_RE.finditer(text)}
    for m in NUMBER_RE.finditer(text):
        weak.add(norm_entity(m.group(1)))
    for rx, canon in SYNONYMS:  # "app verification" and "sideloading" -> one topic entity
        if rx.search(text):
            weak.add(canon.strip())
    return strong, weak


EVENT_CLASSES = {
    "release": r"\b(roll(s|ing)? out|rollout|releas(e|es|ed)|available|out now|arriv(es|ing)|lands?|stable|"
               r"begins?|opens?|starts?|is here|now live|goes? live|goes? global|debuts?|launch(es|ed)?)\b",
    "announce": r"\b(announc(es|ed|ing)?|unveil(s|ed)?|introduc(es|ed)|official(ly)?|reveal(s|ed)?)\b",
    "security": r"\b(security|vulnerab|exploit|zero-day|patch|malware|bulletin|cve-)\w*",
    "price": r"\b(price|pricing|costs?|\$\d)",
    "kill": r"\b(discontinu\w*|shut(s|ting)? down|kill(s|ing|ed)?|end of support|sunset\w*|removes?|dropp(ing|ed)|delet\w*)\b",
    "leak": r"\b(leak\w*|renders?|prototype|fcc|certification|live images|hands-on images|spotted)\b",
    "legal": r"\b(antitrust|lawsuit|court|judge|ruling|fine[sd]?|regulat\w*|ban(s|ned)?)\b",
}
EVENT_RES = {k: re.compile(v, re.I) for k, v in EVENT_CLASSES.items()}


def events(title: str) -> set[str]:
    return {k for k, rx in EVENT_RES.items() if rx.search(title or "")}


HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Item:
    source_id: str
    source_name: str
    outlet: str
    title: str
    url: str
    published: datetime | None
    official: bool
    role: str  # "post" or "corroborate"
    priority: int
    links: list[str] = field(default_factory=list)  # outbound links found in the feed body
    norm_url: str = field(init=False)
    toks: list[str] = field(init=False)
    strong: set[str] = field(init=False)
    weak: set[str] = field(init=False)
    evs: set[str] = field(init=False)
    flags: dict[str, str] = field(default_factory=dict)  # penalty category -> matched text
    bonus: dict[str, str] = field(default_factory=dict)
    relevant: bool = True
    primary_links: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.norm_url = normalize_url(self.url)
        self.toks = tokens(self.title)
        self.strong, self.weak = entities(self.title)
        self.evs = events(self.title)


@dataclass
class Cluster:
    items: list[Item]
    cid: str = ""
    score: float = 0.0
    breakdown: list[str] = field(default_factory=list)
    outlets: list[str] = field(default_factory=list)
    official: bool = False
    big: bool = False
    rep: Item | None = None
    post_url: str = ""
    post_title: str = ""
    skip: str | None = None
    decision: str = ""
    flags: dict[str, str] = field(default_factory=dict)

    @property
    def first_published(self) -> datetime:
        return min(i.published for i in self.items if i.published)

    @property
    def last_published(self) -> datetime:
        return max(i.published for i in self.items if i.published)

    @property
    def all_urls(self) -> set[str]:
        out = {i.norm_url for i in self.items}
        if self.post_url:
            out.add(normalize_url(self.post_url))
        return out


# --------------------------------------------------------------------------
# HTTP + feeds
# --------------------------------------------------------------------------


def http_get(url: str, user_agent: str, accept: str | None = None, timeout: int = 25) -> tuple[int, str, str]:
    headers = {"User-Agent": user_agent}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.geturl(), resp.read().decode("utf-8", errors="replace")


def parse_feed(raw: str) -> list[dict]:
    raw = raw.lstrip("\ufeff")
    root = ET.fromstring(raw)
    items: list[dict] = []
    tag = local_name(root.tag)
    if tag in {"rss", "RDF"}:
        nodes = [n for n in root.iter() if local_name(n.tag) == "item"]
        for node in nodes:
            d = {"title": "", "link": "", "date": "", "body": ""}
            guid = ""
            for child in list(node):
                name = local_name(child.tag)
                text = (child.text or "").strip()
                if name == "title" and not d["title"]:
                    d["title"] = text
                elif name == "link" and not d["link"]:
                    d["link"] = text or child.get("href") or ""
                elif name == "guid" and not guid:
                    guid = text
                elif name in {"pubDate", "date", "published", "updated"} and not d["date"]:
                    d["date"] = text
                elif name in {"description", "encoded", "content", "summary"}:
                    d["body"] += " " + text
            d["link"] = d["link"] or guid
            items.append(d)
    elif tag == "feed":
        for node in root:
            if local_name(node.tag) != "entry":
                continue
            d = {"title": "", "link": "", "date": "", "body": ""}
            alt = ""
            for child in list(node):
                name = local_name(child.tag)
                if name == "title" and not d["title"]:
                    d["title"] = "".join(child.itertext()).strip()
                elif name == "link":
                    href = child.get("href") or (child.text or "").strip()
                    rel = child.get("rel") or "alternate"
                    if href and rel == "alternate" and not alt:
                        alt = href
                    if href and not d["link"]:
                        d["link"] = href
                elif name == "published":
                    d["date"] = (child.text or "").strip()
                elif name == "updated" and not d["date"]:
                    d["date"] = (child.text or "").strip()
                elif name in {"content", "summary"}:
                    d["body"] += " " + ("".join(child.itertext()) or "")
            d["link"] = alt or d["link"]
            items.append(d)
    else:
        raise ValueError(f"Unrecognized feed root: {tag}")
    return items


def make_item(source: dict, title: str, url: str, published: datetime | None, body: str = "") -> Item:
    links = []
    for href in HREF_RE.findall(html.unescape(body or "")):
        if href.startswith("http"):
            links.append(href)
    return Item(
        source_id=source["id"],
        source_name=source.get("name") or source["id"],
        outlet=source.get("outlet") or source["id"],
        title=re.sub(r"\s+", " ", html.unescape(title or "")).strip(),
        url=url,
        published=published,
        official=bool(source.get("official")),
        role=source.get("role") or "post",
        priority=int(source.get("priority") or 1),
        links=links,
    )


def fetch_rss(source: dict, user_agent: str, cache_dir: Path | None, offline: bool) -> list[Item]:
    raw = None
    cache = cache_dir / f"{source['id']}.xml" if cache_dir else None
    if offline and cache and cache.exists():
        raw = cache.read_text(encoding="utf-8", errors="replace")
    else:
        _, _, raw = http_get(source["url"], user_agent,
                             accept="application/rss+xml, application/atom+xml, application/xml, text/xml, */*")
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(raw, encoding="utf-8")
    out = []
    for d in parse_feed(raw):
        link = d.get("link") or ""
        if link.startswith("/"):
            link = urllib.parse.urljoin(source["url"], link)
        out.append(make_item(source, d.get("title") or "", link, parse_dt(d.get("date")), d.get("body") or ""))
    return out


PUBLISHED_RE = re.compile(r"Published\s+([A-Z][a-z]+ \d{1,2}, \d{4})", re.IGNORECASE)


def fetch_asb(source: dict, user_agent: str, now: datetime) -> list[Item]:
    items: list[Item] = []
    year, month = now.year, now.month
    for _ in range(int(source.get("months_back") or 2)):
        url = source["url_template"].format(year=year, month=month)
        title = source["title_template"].format(year=year, month=month,
                                                month_name=datetime(year, month, 1).strftime("%B"))
        try:
            status, final, body = http_get(url, user_agent, accept="text/html")
            published = None
            if status == 200:
                text = html.unescape(re.sub(r"<[^>]+>", " ", body))
                m = PUBLISHED_RE.search(text)
                if m:
                    published = parse_dt(m.group(1))
            items.append(make_item(source, title, final or url, published))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                print(f"! {source['id']}: HTTP {exc.code} for {url}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"! {source['id']}: {exc}", file=sys.stderr)
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return items


def collect_items(config: dict, now: datetime, cache_dir: Path | None = None, offline: bool = False
                  ) -> tuple[list[Item], list[dict]]:
    ua = config["user_agent"]
    items: list[Item] = []
    health: list[dict] = []
    for source in config.get("sources") or []:
        if not source.get("enabled"):
            continue
        kind = source.get("type") or "rss"
        try:
            got = fetch_asb(source, ua, now) if kind == "asb_poll" else fetch_rss(source, ua, cache_dir, offline)
            dated = [i.published for i in got if i.published]
            newest = max(dated) if dated else None
            stale_h = float(source.get("stale_hours") or config.get("feed_stale_hours") or 72)
            status = "ok" if got else "empty"
            if newest and (now - newest) > timedelta(hours=stale_h) and kind != "asb_poll":
                status = f"stale (newest {fmt(newest)})"
            health.append({"id": source["id"], "status": status, "items": len(got), "newest": newest})
            items.extend(got)
        except Exception as exc:  # noqa: BLE001
            health.append({"id": source["id"], "status": f"FAILED: {str(exc)[:120]}", "items": 0, "newest": None})
    return items, health


# --------------------------------------------------------------------------
# Classification: relevance, penalties, bonuses, primary links
# --------------------------------------------------------------------------


class Classifier:
    def __init__(self, config: dict) -> None:
        sc = config["scoring"]
        self.penalty_res = {k: [re.compile(p, re.I) for p in v["patterns"]] for k, v in sc["penalties"].items()}
        self.penalty_pts = {k: float(v["points"]) for k, v in sc["penalties"].items()}
        self.bonus_res = [re.compile(p, re.I) for p in sc["keyword_bonus"]["patterns"]]
        include = (config.get("filters") or {}).get("include_title_or_url") or []
        self.include = [re.compile(p, re.I) for p in include]
        self.primary_domains = [d.lower() for d in config.get("primary_link_domains") or []]
        self.source_cfg = {s["id"]: s for s in config.get("sources") or []}

    def classify(self, item: Item) -> None:
        hay = item.title
        for cat, pats in self.penalty_res.items():
            for p in pats:
                m = p.search(hay)
                if m:
                    item.flags[cat] = m.group(0)
                    break
        for p in self.bonus_res:
            m = p.search(hay)
            if m:
                item.bonus[m.group(0).lower()] = p.pattern
        src = self.source_cfg.get(item.source_id, {})
        need = src.get("require_pattern")
        if need and not re.search(need, f"{item.title} {item.url}", re.I):
            item.relevant = False
        elif item.official and not src.get("require_include", False):
            item.relevant = True
        else:
            item.relevant = any(p.search(f"{item.title} {item.url}") for p in self.include)
        # Outbound links to primary/official pages (layer-1 matching).
        own = urllib.parse.urlparse(item.norm_url).netloc
        for link in item.links:
            n = normalize_url(link)
            host = urllib.parse.urlparse(n).netloc
            if host == own:
                continue
            if any(host == d or host.endswith("." + d) for d in self.primary_domains):
                path = urllib.parse.urlparse(n).path
                # Skip generic pages (home, category, tag, author).
                if path.count("/") < 2 or len(path) < 12 or re.search(r"/(tag|category|author|topics?)/", path):
                    continue
                item.primary_links.add(n)


def drop_boilerplate_links(items: list[Item], max_per_source: int = 2) -> None:
    """A primary link repeated in many items from one source is a sidebar or footer, not a citation."""
    per = Counter()
    for it in items:
        for l in it.primary_links:
            per[(it.source_id, l)] += 1
    for it in items:
        it.primary_links = {l for l in it.primary_links if per[(it.source_id, l)] <= max_per_source}


# --------------------------------------------------------------------------
# Similarity + clustering (layered)
# --------------------------------------------------------------------------


class Similarity:
    def __init__(self, corpus: Iterable[Item], cfg: dict) -> None:
        df = Counter()
        n = 0
        for it in corpus:
            n += 1
            for t in set(it.toks):
                df[t] += 1
        self.n = max(n, 1)
        self.df = df
        self.cfg = cfg

    def idf(self, tok: str) -> float:
        return math.log((self.n + 1) / (self.df.get(tok, 0) + 1)) + 1.0

    def tok_cos(self, a: Iterable[str], b: Iterable[str]) -> float:
        va = Counter(a)
        vb = Counter(b)
        if not va or not vb:
            return 0.0
        dot = sum(self.idf(t) ** 2 * va[t] * vb[t] for t in va if t in vb)
        na = math.sqrt(sum((self.idf(t) * c) ** 2 for t, c in va.items()))
        nb = math.sqrt(sum((self.idf(t) * c) ** 2 for t, c in vb.items()))
        return dot / (na * nb) if na and nb else 0.0

    @staticmethod
    def ent_jaccard(a: Item | dict, b: Item | dict) -> tuple[float, set[str]]:
        sa, wa = (a.strong, a.weak) if isinstance(a, Item) else (set(a["strong"]), set(a["weak"]))
        sb, wb = (b.strong, b.weak) if isinstance(b, Item) else (set(b["strong"]), set(b["weak"]))
        # Company names alone are weak evidence: weight 0.5; strong (versioned) 2; others 1.
        def w(e: str, strong: bool) -> float:
            return 2.0 if strong else (0.5 if e in COMPANY_ENTITIES else 1.0)
        # Company names are excluded: "Google" or "Samsung" alone says nothing
        # about whether two headlines are the same story (they stay in tokens).
        ua = {e: w(e, True) for e in sa} | {e: w(e, False) for e in wa if e not in sa and e not in COMPANY_ENTITIES}
        ub = {e: w(e, True) for e in sb} | {e: w(e, False) for e in wb if e not in sb and e not in COMPANY_ENTITIES}
        keys = set(ua) | set(ub)
        if not keys:
            return 0.0, set()
        inter = set(ua) & set(ub)
        num = sum(max(ua[k], ub[k]) for k in inter)
        den = sum(max(ua.get(k, 0), ub.get(k, 0)) for k in keys)
        shared_strong = inter & (sa | sb)
        j = num / den
        if not shared_strong:
            j *= 0.5  # sharing only "Gemini" or "WhatsApp" is weak evidence
        return j, shared_strong

    def score(self, a: Item | dict, b: Item | dict) -> tuple[float, str]:
        """Return (similarity 0..1+, reason). Item-Item results are memoised."""
        if isinstance(a, Item) and isinstance(b, Item):
            key = (id(a), id(b)) if id(a) < id(b) else (id(b), id(a))
            memo = self.__dict__.setdefault("_memo", {})
            if key not in memo:
                memo[key] = self._score(a, b)
            return memo[key]
        return self._score(a, b)

    def _score(self, a: Item | dict, b: Item | dict) -> tuple[float, str]:
        c = self.cfg
        la = a.primary_links if isinstance(a, Item) else set(a.get("primary_links") or [])
        lb = b.primary_links if isinstance(b, Item) else set(b.get("primary_links") or [])
        ua = a.norm_url if isinstance(a, Item) else a.get("norm_url", "")
        ub = b.norm_url if isinstance(b, Item) else b.get("norm_url", "")
        # Layer 1: shared primary link, or one item IS the other's primary source.
        ta = a.toks if isinstance(a, Item) else a["toks"]
        tb = b.toks if isinstance(b, Item) else b["toks"]
        tc = self.tok_cos(ta, tb)
        if (la & lb) or (ua and ua in lb) or (ub and ub in la):
            # Articles also cite old background links; demand a little headline overlap.
            if tc >= c["link_tok_min"]:
                return 1.0, f"shared primary link (tok={tc:.2f})"
        ej, shared_strong = self.ent_jaccard(a, b)
        ea = a.evs if isinstance(a, Item) else set(a.get("evs") or [])
        eb = b.evs if isinstance(b, Item) else set(b.get("evs") or [])
        sim = c["w_entity"] * ej + c["w_tokens"] * tc
        why = f"ent={ej:.2f} tok={tc:.2f}"
        if isinstance(a, Item) and isinstance(b, Item) and (("deal" in a.flags) != ("deal" in b.flags)):
            # A deal post and a news post about the same phone are different stories.
            sim -= c["framing_mismatch_penalty"]
            why += " -framing(deal vs news)"
        if tc < c["tok_min"]:
            return min(sim, c["threshold"] - 0.01), why + " (tok below floor)"
        if tc >= c["tok_alone"] and not shared_strong:
            sim = max(sim, c["threshold"])
            why += " (headlines alone match)"
        if shared_strong:
            # Over-merge guard for launch days: a shared product/version alone
            # ("One UI 9.5") is not enough. Need overlap beyond the entity words.
            ent_words = {t for t in set(ta) | set(tb) if any(t and t in e for e in shared_strong)}
            ra = [t for t in ta if t not in ent_words]
            rb = [t for t in tb if t not in ent_words]
            rc = self.tok_cos(ra, rb)
            why += f" resid={rc:.2f}"
            if ea & eb and rc >= c["event_resid_min"]:
                sim += c["event_bonus"]
                why += f" +event({','.join(sorted(ea & eb))})"
            elif rc < c["resid_min"] and tc < c["guard_tok_max"]:
                sim = min(sim, c["threshold"] - 0.01)
                why += " guard(same-product,different-story)"
        return sim, why


def cluster_items(items: list[Item], sim: Similarity, cfg: dict) -> list[Cluster]:
    """Greedy, time-ordered clustering. Each item joins the existing cluster
    whose best-matching member (within the time window) is most similar."""
    window = timedelta(hours=float(cfg["window_hours"]))
    link_window = timedelta(hours=float(cfg.get("link_window_hours") or cfg["window_hours"]))
    thr = float(cfg["threshold"])
    clusters: list[Cluster] = []
    for it in sorted(items, key=lambda i: i.published):
        # Exact URL duplicates (same article in two feeds of one outlet) always join.
        best, best_s, best_why = None, 0.0, ""
        for cl in clusters:
            if it.norm_url in cl.all_urls:
                best, best_s, best_why = cl, 9.9, "same url"
                break
            for m in cl.items:
                gap = abs(it.published - m.published)
                if gap > window:
                    # Layer 1 (shared primary/official link) may reach further back:
                    # coverage of an official post often lands the next day.
                    if gap > link_window or not (it.primary_links & m.primary_links or it.norm_url in m.primary_links
                                                 or m.norm_url in it.primary_links):
                        continue
                    s, why = sim.score(it, m)
                    if not why.startswith("shared primary"):
                        continue
                else:
                    s, why = sim.score(it, m)
                if s > best_s:
                    best, best_s, best_why = cl, s, why
        if best is not None and best_s >= thr:
            best.items.append(it)
            it.flags.setdefault("_joined", f"{best_s:.2f} {best_why}")
        else:
            clusters.append(Cluster(items=[it]))
    for n, cl in enumerate(clusters):
        cl.cid = f"c{n:03d}"
    return clusters


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def score_cluster(cl: Cluster, cfg: dict, now: datetime) -> None:
    sc = cfg["scoring"]
    pen_pts = {k: float(v["points"]) for k, v in sc["penalties"].items()}
    outlets = sorted({i.outlet for i in cl.items if not i.official})
    cl.outlets = outlets
    cl.official = any(i.official for i in cl.items)
    parts: list[str] = []
    s = float(sc["per_outlet"]) * len(outlets)
    parts.append(f"{len(outlets)} outlet(s) x{sc['per_outlet']}")
    if cl.official:
        s += float(sc["official_bonus"])
        parts.append(f"official +{sc['official_bonus']}")
    kws = {}
    for i in cl.items:
        kws.update(i.bonus)
    if kws:
        kb = min(len(kws) * float(sc["keyword_bonus"]["points_each"]), float(sc["keyword_bonus"]["max"]))
        s += kb
        parts.append(f"keywords {sorted(kws)[:3]} +{kb:g}")
    # Penalties: a story's framing is its BEST framing. If one outlet calls it
    # a deal and another reports it as news, it is news. So take penalties
    # from the least-penalised item that is eligible to be posted.
    def item_pen(i: Item) -> float:
        return sum(pen_pts[k] for k in i.flags if not k.startswith("_"))
    # Use the MEDIAN item's framing (lower median on ties, i.e. the kinder
    # one): one outlet calling a story a "deal" does not make it a deal, and
    # one news item wrongly merged into a deals cluster does not clean it.
    eligible = sorted([i for i in cl.items if i.relevant] or cl.items, key=item_pen, reverse=True)
    best = eligible[(len(eligible) - 1) // 2]
    pen = item_pen(best)
    flags = {k: v for k, v in best.flags.items() if not k.startswith("_")}
    rumor = "rumor" in flags
    if rumor:
        # Single-source rumor is penalised harder than a widely reported one.
        extra = float(sc["rumor_single_source_extra"]) if len(outlets) <= 1 else 0.0
        pen += extra
    if pen:
        s += pen
        parts.append("penalties " + ", ".join(f"{k}('{v}')" for k, v in flags.items()) + f" {pen:+g}")
    cl.score = round(s, 2)
    cl.breakdown = parts
    cl.flags = flags
    cl.big = (
        len(outlets) + (1 if cl.official and sc.get("official_counts_as_outlet") else 0) >= int(sc["big_min_outlets"])
        and cl.score >= float(sc["big_score"])
        and not (rumor and not sc.get("rumor_can_be_big", False))
        and not any(k in flags for k in sc.get("never_big", []))
    )


def pick_representative(cl: Cluster, cfg: dict, resolve_primary: bool, ua: str) -> None:
    """Choose the link to post: official item > cited primary source (if its
    page title can be read) > earliest clean item from a good outlet."""
    sc = cfg["scoring"]
    pen_pts = {k: float(v["points"]) for k, v in sc["penalties"].items()}
    postable = [i for i in cl.items if i.role == "post" and i.relevant]
    cited = Counter(l for i in cl.items for l in i.primary_links)
    min_cites = int(cfg.get("primary_min_citations") or 2)
    # Official candidates: official items in the cluster, plus official-feed
    # posts that cluster members link to. Most-cited wins, then earliest.
    offi = {i.norm_url: i for i in postable if i.official}
    for l in cited:
        if l in OFFICIAL_INDEX:
            offi.setdefault(l, OFFICIAL_INDEX[l])
    if offi:
        cl.rep = min(offi.values(), key=lambda i: (-cited.get(i.norm_url, 0), i.published))
        cl.post_url, cl.post_title = cl.rep.url, cl.rep.title
        return
    if resolve_primary and cited:
        link, n = cited.most_common(1)[0]
        if n >= min_cites:
            title = fetch_page_title(link, ua)
            if title:
                cl.rep = None
                cl.post_url, cl.post_title = link, title
                return
    if not postable:
        cl.rep = None
        return
    # Among clean items from preferred outlets, take the most "central"
    # headline (most similar to the rest of the cluster: the typical framing,
    # not a preview or a side-angle), then the earliest.
    sim = SIM_REF[0] if SIM_REF else None
    def central(i: Item) -> float:
        if not sim or len(cl.items) < 3:
            return 0.0
        return round(sum(sim.score(i, o)[0] for o in cl.items if o is not i) / (len(cl.items) - 1), 1)
    def key(i: Item) -> tuple:
        pen = sum(pen_pts[k] for k in i.flags if not k.startswith("_"))
        return (pen < 0, -min(i.priority, 2), -central(i), i.published)
    cl.rep = min(postable, key=key)
    cl.post_url, cl.post_title = cl.rep.url, cl.rep.title


_TITLE_CACHE: dict[str, str | None] = {}
OFFICIAL_INDEX: dict[str, Item] = {}  # norm_url -> item from an official feed (any age)
SIM_REF: list = []  # the current Similarity, for representative choice


def fetch_page_title(url: str, ua: str) -> str | None:
    if url in _TITLE_CACHE:
        return _TITLE_CACHE[url]
    title = None
    try:
        _, _, body = http_get(url, ua, accept="text/html", timeout=8)
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', body, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title', body, re.I) or \
            re.search(r"<title[^>]*>([^<]+)</title>", body, re.I)
        if m:
            title = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
            title = re.sub(r"\s+[|\-–]\s+(Google|Samsung|Android Developers|The Keyword|Samsung Global Newsroom).*$", "", title)
    except Exception:  # noqa: BLE001
        title = None
    _TITLE_CACHE[url] = title
    return title


# --------------------------------------------------------------------------
# Lemmy
# --------------------------------------------------------------------------


class Lemmy:
    def __init__(self, api_base: str, user_agent: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.user_agent = user_agent
        self._jwt: str | None = None

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> Any:
        url = self.api_base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self._jwt:
            headers["Authorization"] = f"Bearer {self._jwt}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise RuntimeError(f"Lemmy {method} {path} failed: HTTP {exc.code} {detail}") from exc

    def login(self, username: str, password: str) -> None:
        data = self._request("POST", "/user/login", body={"username_or_email": username, "password": password})
        if not data.get("jwt"):
            raise RuntimeError("Login did not return a token")
        self._jwt = data["jwt"]

    def community_id(self, name: str) -> int:
        return int(self._request("GET", "/community", params={"name": name})["community_view"]["community"]["id"])

    def recent_posts(self, community: str, hours: float, max_pages: int = 4) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            data = self._request("GET", "/post/list", params={
                "community_name": community, "sort": "New", "type_": "All", "limit": 50, "page": page})
            posts = data.get("posts") or []
            for e in posts:
                p = e.get("post") or {}
                pub = parse_dt(p.get("published"))
                if p.get("featured_community") or p.get("featured_local"):
                    continue  # pinned posts are old; ignore for time cutoff
                if pub and pub < cutoff:
                    return out
                out.append(e)
            if len(posts) < 50:
                break
        return out

    def create_post(self, community_id: int, title: str, url: str) -> dict:
        return self._request("POST", "/post", body={"name": title[:200], "url": url,
                                                    "community_id": community_id, "nsfw": False})


def lemmy_post_records(posts: list[dict]) -> list[dict]:
    recs = []
    for e in posts:
        p = e.get("post") or {}
        if p.get("removed") or p.get("deleted"):
            continue
        title = p.get("name") or ""
        it_strong, it_weak = entities(title)
        recs.append({
            "title": title,
            "norm_url": normalize_url(p.get("url") or ""),
            "toks": tokens(title),
            "strong": sorted(it_strong),
            "weak": sorted(it_weak),
            "evs": sorted(events(title)),
            "primary_links": [],
            "when": (parse_dt(p.get("published")) or datetime.now(timezone.utc)).isoformat(),
            "by": (e.get("creator") or {}).get("name") or "?",
        })
    return recs


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"version": 2, "posted": [], "first_seen": {}}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def prune_state(state: dict, now: datetime, hours: float) -> None:
    cutoff = now - timedelta(hours=hours)
    state["posted"] = [p for p in state.get("posted", []) if parse_dt(p["posted_at"]) >= cutoff]
    fs = state.get("first_seen", {})
    state["first_seen"] = {k: v for k, v in fs.items() if parse_dt(v) >= now - timedelta(hours=72)}


def record_from_cluster(cl: Cluster, now: datetime) -> dict:
    rep_strong, rep_weak = entities(cl.post_title)
    return {
        "title": cl.post_title,
        "url": cl.post_url,
        "norm_url": normalize_url(cl.post_url),
        "cluster_urls": sorted(cl.all_urls),
        "toks": tokens(cl.post_title),
        "strong": sorted(rep_strong | set().union(*(i.strong for i in cl.items))),
        "weak": sorted(rep_weak),
        "evs": sorted(events(cl.post_title)),
        "primary_links": sorted(set().union(*(i.primary_links for i in cl.items))),
        "score": cl.score,
        "big": cl.big,
        "outlets": cl.outlets,
        "posted_at": now.isoformat(),
        "when": now.isoformat(),
        "by": "AndroidNews(v2)",
    }


# --------------------------------------------------------------------------
# The decision engine (one poll)
# --------------------------------------------------------------------------


def dedupe_hit(cl: Cluster, records: list[dict], sim: Similarity, thr: float, label: str) -> str | None:
    urls = cl.all_urls
    for r in records:
        rurls = set(r.get("cluster_urls") or []) | {r.get("norm_url")}
        if urls & rurls:
            return f"duplicate url ({label}: '{r['title'][:70]}' by {r['by']} {fmt(parse_dt(r['when']))})"
    for r in records:
        for it in cl.items:
            s, why = sim.score(it, r)
            if s >= thr:
                return f"same story ({label}: '{r['title'][:70]}' by {r['by']}, sim {s:.2f} {why})"
    return None


def in_quiet_hours(now: datetime, cfg: dict) -> bool:
    q = cfg["schedule"]["quiet_hours_pt"]
    h = now.astimezone(PT).hour
    start, end = int(q[0]), int(q[1])
    return start <= h < end if start < end else (h >= start or h < end)


def decide(
    items: list[Item],
    cfg: dict,
    state: dict,
    lemmy_records: list[dict],
    now: datetime,
    sim: Similarity,
    resolve_primary: bool = True,
) -> tuple[list[Cluster], list[Cluster]]:
    """Return (to_post, all_clusters_considered). Mutates nothing."""
    sched = cfg["schedule"]
    clu = cfg["clustering"]
    lookback = timedelta(hours=float(sched["candidate_window_hours"]))
    visible = [i for i in items if i.published and now - lookback <= i.published <= now and i.title and i.norm_url]
    clusters = cluster_items(visible, sim, clu)
    for cl in clusters:
        score_cluster(cl, cfg, now)
    posted = state.get("posted", [])
    posted24 = [p for p in posted if parse_dt(p["posted_at"]) > now - timedelta(hours=24)]
    last_post = max((parse_dt(p["posted_at"]) for p in posted), default=None)
    cap = int(sched["rolling_cap_24h"])
    hard_cap = cap + int(sched["big_overflow"])
    min_gap = timedelta(minutes=float(sched["min_gap_minutes"]))
    dwell = timedelta(minutes=float(sched["ordinary_min_dwell_minutes"]))
    dedupe_thr = float(clu.get("dedupe_threshold") or clu["threshold"])
    max_age_ord = timedelta(hours=float(sched["ordinary_max_age_hours"]))
    max_age_big = timedelta(hours=float(sched["big_max_age_hours"]))
    min_score = float(cfg["scoring"]["post_min_score"])

    # Topic fatigue: an ordinary story about a product we already posted about
    # in the last N hours loses points (keeps One UI beta day from becoming
    # five One UI posts). Big stories are exempt.
    fat_h = float(cfg["scoring"].get("topic_fatigue_hours") or 0)
    fat_pts = float(cfg["scoring"].get("topic_fatigue_points") or 0)
    if fat_h and fat_pts:
        recent_ents = [set(p.get("strong") or []) for p in posted
                       if parse_dt(p["posted_at"]) > now - timedelta(hours=fat_h)]
        for cl in clusters:
            if cl.big:
                continue
            ents = set().union(*(i.strong for i in cl.items))
            hits = sum(1 for r in recent_ents if ents & r)
            if hits:
                cl.score = round(cl.score + fat_pts * min(hits, 2), 2)
                cl.breakdown.append(f"topic fatigue x{min(hits, 2)} {fat_pts * min(hits, 2):+g}")
    # Fill mode: on a slow day, after `fill_after_hours` without any post,
    # clean single-source stories (score >= fill_min_score, no penalties) may post.
    fill_after = float(sched.get("fill_after_hours") or 0)
    fill_min = float(cfg["scoring"].get("fill_min_score") or min_score)
    fill_mode = bool(fill_after) and not in_quiet_hours(now, cfg) and (
        last_post is None or now - last_post >= timedelta(hours=fill_after))
    big_c, ord_c = [], []
    for cl in clusters:
        age = now - cl.first_published        # for the dwell time
        fresh = now - cl.last_published       # a story still being picked up stays fresh
        if not any(i.relevant for i in cl.items):
            cl.skip = "not Android-related"
            continue
        hit = dedupe_hit(cl, posted, sim, dedupe_thr, "we posted") or \
            dedupe_hit(cl, lemmy_records, sim, dedupe_thr, "on !android")
        if hit:
            cl.skip = hit
            continue
        hard = [k for k in cl.flags if k in cfg["scoring"].get("hard_exclude", [])]
        if hard:
            cl.skip = f"excluded ({', '.join(hard)})"
            continue
        if cl.score < min_score and not (fill_mode and cl.score >= fill_min and not cl.flags):
            cl.skip = f"score {cl.score} < {min_score}" + (f" (fill mode needs {fill_min} and no penalties)" if fill_mode else "")
            continue
        if cl.big:
            if fresh > max_age_big:
                cl.skip = f"big but stale (newest item {fresh.total_seconds()/3600:.1f}h old)"
                continue
            big_c.append(cl)
        else:
            if fresh > max_age_ord:
                cl.skip = f"stale (newest item {fresh.total_seconds()/3600:.1f}h > {max_age_ord.total_seconds()/3600:g}h)"
                continue
            if age < dwell:
                cl.skip = f"dwell: waiting for corroboration ({int(age.total_seconds()//60)}m < {int(dwell.total_seconds()//60)}m)"
                continue
            ord_c.append(cl)

    to_post: list[Cluster] = []
    count = len(posted24)
    ua = cfg["user_agent"]
    for cl in sorted(big_c, key=lambda c: -c.score):
        pick_representative(cl, cfg, resolve_primary, ua)
        if not cl.post_url:
            cl.skip = "no postable link (only corroborating sources)"
            continue
        if count >= hard_cap:
            cl.skip = f"BIG but hard cap {hard_cap}/24h reached"
            continue
        cl.decision = "POST (big)"
        to_post.append(cl)
        count += 1

    # Ordinary: one per poll at most, best ranked, gap + quiet hours + cap.
    def rank(c: Cluster) -> float:
        hours = (now - c.first_published).total_seconds() / 3600
        return c.score - float(sched["age_decay_per_hour"]) * hours
    ord_c.sort(key=rank, reverse=True)
    blocker = None
    if in_quiet_hours(now, cfg):
        blocker = "quiet hours (PT)"
    elif count >= cap:
        blocker = f"rolling cap {cap}/24h reached"
    elif last_post and now - last_post < min_gap and not to_post:
        blocker = f"min gap ({int((now - last_post).total_seconds()//60)}m < {int(min_gap.total_seconds()//60)}m)"
    elif to_post:
        blocker = "a big story posted this poll"
    posted_one = False
    for cl in ord_c:
        if blocker or posted_one:
            cl.skip = f"queued (rank {rank(cl):.2f}): {blocker or 'one ordinary post per poll'}"
            continue
        pick_representative(cl, cfg, resolve_primary, ua)
        if not cl.post_url:
            cl.skip = "no postable link (only corroborating sources)"
            continue
        cl.decision = f"POST (ordinary, rank {rank(cl):.2f})"
        to_post.append(cl)
        posted_one = True
    return to_post, clusters


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def describe(cl: Cluster) -> str:
    lines = [f"[{cl.cid}] score {cl.score:g}{' BIG' if cl.big else ''}  outlets={','.join(cl.outlets) or '-'}"
             f"{' +official' if cl.official else ''}  first={fmt(cl.first_published)}",
             f"    why: {'; '.join(cl.breakdown)}"]
    if cl.decision:
        lines.append(f"    -> {cl.decision}: {cl.post_title}")
        lines.append(f"       {cl.post_url}")
    else:
        lines.append(f"    skip: {cl.skip}")
    for i in sorted(cl.items, key=lambda x: x.published):
        lines.append(f"    - {fmt(i.published)} [{i.source_id}] {i.title[:110]}")
    return "\n".join(lines)


def print_poll(now: datetime, health: list[dict], clusters: list[Cluster], to_post: list[Cluster],
               state: dict, dry: bool, verbose: bool) -> None:
    print(f"AndroidNews v2 — {'DRY RUN' if dry else 'POST'}  now={fmt2(now)}")
    bad = [h for h in health if h["status"] != "ok"]
    print(f"feeds: {len(health)} ({len(health) - len(bad)} ok)" + "".join(f"\n  ! {h['id']}: {h['status']}" for h in bad))
    p24 = [p for p in state.get("posted", []) if parse_dt(p["posted_at"]) > now - timedelta(hours=24)]
    print(f"rolling 24h posts: {len(p24)}")
    print(f"clusters: {len(clusters)}  to post: {len(to_post)}")
    for cl in to_post:
        print(describe(cl))
    shown = [c for c in clusters if c not in to_post and (verbose or (c.skip and (
        c.skip.startswith("queued") or c.skip.startswith("dwell") or "BIG" in c.skip or c.big)))]
    if shown:
        print("considered:")
        for cl in sorted(shown, key=lambda c: -c.score)[: (999 if verbose else 15)]:
            print(describe(cl))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def prepare(items: list[Item], cfg: dict) -> Similarity:
    set_synonyms(cfg.get("synonyms"))
    for it in items:  # recompute tokens/entities with synonyms applied
        it.toks = tokens(it.title)
        it.strong, it.weak = entities(it.title)
    OFFICIAL_INDEX.clear()
    OFFICIAL_INDEX.update({it.norm_url: it for it in items if it.official})
    clf = Classifier(cfg)
    for it in items:
        clf.classify(it)
    drop_boilerplate_links(items)
    sim = Similarity(items, cfg["clustering"])
    SIM_REF[:] = [sim]
    return sim


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AndroidNews v2 poster for lemdro.id")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--state", default=None)
    ap.add_argument("--post", action="store_true", help="Actually post (needs $ANDROIDNEWS_PASSWORD)")
    ap.add_argument("--verbose", "-v", action="store_true", help="Show every cluster and why")
    ap.add_argument("--feed-cache", default=None, help="Save raw feeds here (and read them with --offline)")
    ap.add_argument("--offline", action="store_true", help="Read feeds from --feed-cache instead of fetching")
    ap.add_argument("--lemmy-ua", default=None, help="Override User-Agent for Lemmy reads")
    ap.add_argument("--no-resolve-primary", action="store_true", help="Do not fetch cited primary pages for titles")
    args = ap.parse_args(argv)

    dry = not args.post
    cfg_path = Path(args.config).expanduser()
    cfg = yaml.safe_load(cfg_path.read_text())
    state_path = Path(args.state) if args.state else cfg_path.parent / (cfg.get("state_file") or "state-v2.json")
    now = datetime.now(timezone.utc)

    items, health = collect_items(cfg, now, Path(args.feed_cache) if args.feed_cache else None, args.offline)
    sim = prepare(items, cfg)
    state = load_state(state_path)
    prune_state(state, now, float(cfg["schedule"]["dedupe_hours"]))

    community = cfg.get("community") or "android"
    lemmy = Lemmy(cfg["api_base"], args.lemmy_ua or cfg["user_agent"])
    try:
        recs = lemmy_post_records(lemmy.recent_posts(community, float(cfg["schedule"]["dedupe_hours"])))
    except Exception as exc:  # noqa: BLE001
        # Without the community check we could repost a human's link. Fail closed.
        print(f"Cannot read !{community} for dedupe ({exc}); not posting this poll.", file=sys.stderr)
        return 1

    # Our own account's posts on !android count toward the rolling cap and the
    # gap even if they are missing from state (v1 cutover, lost state file).
    me = (cfg.get("username") or "AndroidNews").lower()
    known = {p.get("norm_url") for p in state.get("posted", [])}
    for r in recs:
        if r["by"].lower() == me and r["norm_url"] not in known:
            state.setdefault("posted", []).append(dict(r, posted_at=r["when"], cluster_urls=[r["norm_url"]]))
    to_post, clusters = decide(items, cfg, state, recs, now, sim, resolve_primary=not args.no_resolve_primary)
    print_poll(now, health, clusters, to_post, state, dry, args.verbose)
    if dry or not to_post:
        return 0

    pw = os.environ.get(cfg.get("password_env") or "ANDROIDNEWS_PASSWORD")
    if not pw:
        print("Refusing to post: password env var is not set", file=sys.stderr)
        return 2
    lemmy.user_agent = cfg["user_agent"]
    lemmy.login(cfg.get("username") or "AndroidNews", pw)
    cid = lemmy.community_id(community)
    errors = 0
    for cl in to_post:
        try:
            lemmy.create_post(cid, cl.post_title, cl.post_url)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to post {cl.post_url}: {exc}", file=sys.stderr)
            errors += 1
            continue
        print(f"Posted to !{community}: {cl.post_title}  (score {cl.score}{', big' if cl.big else ''})")
        state.setdefault("posted", []).append(record_from_cluster(cl, now))
        save_state(state_path, state)
    save_state(state_path, state)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
