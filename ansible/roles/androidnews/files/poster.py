#!/usr/bin/env python3
"""Android news poster for lemdro.id.

Default mode is --dry-run: print what would be posted and why items
were skipped. Real posting requires --post and ANDROIDNEWS_PASSWORD
(see config). Never prints passwords or JWTs.

Posts use the original headline and link only. No generated summaries.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import yaml
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent


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


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("/"):
        return url.rstrip("/") or "/"
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    drop = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "s",
    }
    pairs = []
    for key, values in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower() not in drop:
            for value in values if isinstance(values, list) else [values]:
                pairs.append((key, value))
    query = urllib.parse.urlencode(sorted(pairs))
    path = parsed.path.rstrip("/") or "/"
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}{path}" + (f"?{query}" if query else "")


def title_fingerprint(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"\[(.*?)\]", " ", text)
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split() if w not in {"the", "a", "an", "and", "of", "to", "for", "in", "on"}]
    return " ".join(words[:12])


def format_pt(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
    abbrev = local.tzname() or "PT"
    return local.strftime(f"%Y-%m-%d %H:%M {abbrev}")


@dataclass
class Item:
    source_id: str
    source_name: str
    title: str
    url: str
    published: datetime | None
    official: bool
    community: str
    skip_reason: str | None = None
    norm_url: str = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        self.norm_url = normalize_url(self.url)
        self.fingerprint = title_fingerprint(self.title)


class Lemmy:
    def __init__(self, api_base: str, user_agent: str, jwt: str | None = None) -> None:
        self.api_base = api_base.rstrip("/")
        self.user_agent = user_agent
        self.jwt = jwt

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> Any:
        url = self.api_base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if self.jwt:
            headers["Authorization"] = f"Bearer {self.jwt}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"Lemmy {method} {path} failed: HTTP {exc.code} {detail}") from exc

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params)

    def login(self, username: str, password: str) -> None:
        data = self._request("POST", "/user/login", body={"username_or_email": username, "password": password})
        token = data.get("jwt")
        if not token:
            raise RuntimeError("Login did not return a token")
        self.jwt = token

    def community_id(self, name: str) -> int:
        data = self.get("/community", name=name)
        return int(data["community_view"]["community"]["id"])

    def recent_posts(self, community_id: int, lookback_hours: int, max_pages: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - lookback_hours * 3600
        collected: list[dict] = []
        for page in range(1, max_pages + 1):
            data = self.get(
                "/post/list",
                community_id=community_id,
                sort="New",
                type_="All",
                limit=50,
                page=page,
            )
            posts = data.get("posts") or []
            if not posts:
                break
            stop = False
            for entry in posts:
                post = entry.get("post") or {}
                published = parse_dt(post.get("published"))
                if published and published.timestamp() < cutoff and page > 1:
                    stop = True
                    break
                collected.append(entry)
            if stop or len(posts) < 50:
                break
        return collected

    def create_post(self, community_id: int, title: str, url: str) -> dict:
        return self._request(
            "POST",
            "/post",
            body={"name": title, "url": url, "community_id": community_id, "nsfw": False},
        )


def http_get(url: str, user_agent: str, accept: str | None = None) -> tuple[int, str, str]:
    headers = {"User-Agent": user_agent}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.status, resp.geturl(), resp.read().decode("utf-8", errors="replace")


def parse_feed(raw: str) -> list[dict]:
    raw = raw.lstrip("\ufeff")
    root = ET.fromstring(raw)
    items: list[dict] = []
    tag = local_name(root.tag)
    if tag in {"rss", "RDF"}:
        for node in root.iter():
            if local_name(node.tag) != "item":
                continue
            title = link = date = guid = ""
            for child in list(node):
                name = local_name(child.tag)
                if name == "title" and not title:
                    title = (child.text or "").strip()
                elif name == "link" and not link:
                    link = (child.text or child.get("href") or "").strip()
                elif name == "guid" and not guid:
                    guid = (child.text or "").strip()
                elif name in {"pubDate", "date", "updated", "published"} and not date:
                    date = (child.text or "").strip()
            items.append({"title": title, "link": link or guid, "date": date})
    elif tag == "feed":
        for node in root:
            if local_name(node.tag) != "entry":
                continue
            title = link = date = alt = ""
            for child in list(node):
                name = local_name(child.tag)
                if name == "title" and not title:
                    title = (child.text or "").strip()
                elif name == "link":
                    href = child.get("href") or (child.text or "").strip()
                    rel = child.get("rel") or "alternate"
                    if href and rel in {"alternate", None, ""} and not alt:
                        alt = href
                    if href and not link:
                        link = href
                elif name == "published":
                    date = (child.text or "").strip()
                elif name == "updated" and not date:
                    date = (child.text or "").strip()
            items.append({"title": title, "link": alt or link, "date": date})
    else:
        raise ValueError(f"Unrecognized feed root: {tag}")
    return items


def fetch_rss_items(source: dict, user_agent: str) -> list[Item]:
    _, _, body = http_get(
        source["url"],
        user_agent,
        accept="application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    )
    items = []
    base = source["url"]
    for raw in parse_feed(body):
        link = raw.get("link") or ""
        if link.startswith("/"):
            link = urllib.parse.urljoin(base, link)
        items.append(
            Item(
                source_id=source["id"],
                source_name=source.get("name") or source["id"],
                title=re.sub(r"\s+", " ", (raw.get("title") or "").strip()),
                url=link,
                published=parse_dt(raw.get("date")),
                official=bool(source.get("official")),
                community=source.get("community") or "",
            )
        )
    return items


PUBLISHED_RE = re.compile(
    r"Published\s+([A-Z][a-z]+ \d{1,2}, \d{4})",
    re.IGNORECASE,
)


def fetch_asb_items(source: dict, user_agent: str, now: datetime) -> list[Item]:
    months_back = int(source.get("months_back") or 2)
    items: list[Item] = []
    year = now.year
    month = now.month
    for _ in range(months_back):
        url = source["url_template"].format(year=year, month=month)
        title = source["title_template"].format(
            year=year,
            month=month,
            month_name=datetime(year, month, 1).strftime("%B"),
        )
        try:
            status, final, body = http_get(url, user_agent, accept="text/html,application/xhtml+xml")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                print(f"! {source['id']}: HTTP {exc.code} for {url}", file=sys.stderr)
            # Step back a month and continue.
            month -= 1
            if month == 0:
                month = 12
                year -= 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"! {source['id']}: {exc}", file=sys.stderr)
            month -= 1
            if month == 0:
                month = 12
                year -= 1
            continue
        published = None
        if status == 200:
            text = re.sub(r"<[^>]+>", " ", body)
            text = re.sub(r"&#39;", "'", text)
            text = re.sub(r"&amp;", "&", text)
            match = PUBLISHED_RE.search(text)
            if match:
                published = parse_dt(match.group(1))
        items.append(
            Item(
                source_id=source["id"],
                source_name=source.get("name") or source["id"],
                title=title,
                url=final or url,
                published=published,
                official=True,
                community=source.get("community") or "",
            )
        )
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return items


def compile_filters(config: dict) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    filters = config.get("filters") or {}
    exclude = [re.compile(raw, re.IGNORECASE) for raw in filters.get("exclude_title") or []]
    include = [re.compile(raw, re.IGNORECASE) for raw in filters.get("include_title_or_url") or []]
    return exclude, include


def excluded_by_filter(
    item: Item,
    exclude: list[re.Pattern[str]],
    include: list[re.Pattern[str]],
) -> str | None:
    if item.official:
        return None
    haystack = f"{item.title} {item.url}"
    for pat in exclude:
        if pat.search(haystack):
            return f"title filter /{pat.pattern}/"
    if include and not any(pat.search(haystack) for pat in include):
        return "not Android-related (include filter)"
    return None


class DedupeIndex:
    def __init__(self) -> None:
        self.urls: dict[str, str] = {}
        self.fingerprints: dict[str, str] = {}

    def add(self, url: str, title: str, label: str) -> None:
        norm = normalize_url(url)
        fp = title_fingerprint(title)
        if norm:
            self.urls[norm] = label
        if fp:
            self.fingerprints[fp] = label

    def hit(self, item: Item) -> str | None:
        if item.norm_url and item.norm_url in self.urls:
            return f"duplicate url ({self.urls[item.norm_url]})"
        if item.fingerprint and item.fingerprint in self.fingerprints:
            return f"duplicate title ({self.fingerprints[item.fingerprint]})"
        return None


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"seen": {}, "posted_on": {}}
    return json.loads(path.read_text())


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def build_index_from_community(posts: list[dict]) -> DedupeIndex:
    index = DedupeIndex()
    for entry in posts:
        post = entry.get("post") or {}
        if post.get("removed") or post.get("deleted"):
            continue
        url = post.get("url") or ""
        title = post.get("name") or ""
        creator = (entry.get("creator") or {}).get("name") or "unknown"
        published = post.get("published") or ""
        index.add(url, title, f"already on lemdro.id by {creator} at {published[:19]}")
    return index


def collect_items(config: dict, now: datetime) -> tuple[list[Item], list[str]]:
    user_agent = config["user_agent"]
    default_community = config.get("default_community") or "android"
    notes: list[str] = []
    items: list[Item] = []
    for source in config.get("sources") or []:
        if not source.get("enabled"):
            continue
        source = dict(source)
        source["community"] = source.get("community") or default_community
        kind = source.get("type") or "rss"
        try:
            if kind == "asb_poll":
                fetched = fetch_asb_items(source, user_agent, now)
            else:
                fetched = fetch_rss_items(source, user_agent)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{source['id']}: failed to fetch ({exc})")
            continue
        notes.append(f"{source['id']}: fetched {len(fetched)} item(s)")
        items.extend(fetched)
    return items, notes


def select_posts(
    items: list[Item],
    config: dict,
    index: DedupeIndex,
    state: dict,
    now: datetime,
    lookback_hours: int,
    per_published_day: bool = True,
) -> tuple[list[Item], list[Item]]:
    exclude, include = compile_filters(config)
    cutoff = now.timestamp() - lookback_hours * 3600
    tz = ZoneInfo(config.get("day_timezone") or "America/Los_Angeles")
    today = now.astimezone(tz).date().isoformat()
    posted_on = dict(state.get("posted_on") or {})
    cap = int(config.get("max_posts_per_day") or 5)
    # Dry-run applies the cap per published calendar day, as if the bot had been
    # running daily. Real posts all count against today.
    # per_published_day: dry-run uses each item's published day; --post uses today.

    # Prefer official items, then older first so a catch-up run is chronological.
    ranked = sorted(
        items,
        key=lambda it: (
            0 if it.official else 1,
            it.published or now,
            it.title.lower(),
        ),
    )

    accepted: list[Item] = []
    skipped: list[Item] = []
    seen_this_run = DedupeIndex()
    used_on: dict[str, int] = {}

    for item in ranked:
        reason = None
        if not item.title or not item.norm_url:
            reason = "missing title or url"
        elif item.published is None:
            reason = "no published date"
        elif item.published.timestamp() < cutoff:
            reason = f"older than lookback ({format_pt(item.published)})"
        if not reason:
            reason = excluded_by_filter(item, exclude, include)
        if not reason:
            reason = index.hit(item)
        if not reason:
            reason = seen_this_run.hit(item)
        if not reason and item.norm_url in (state.get("seen") or {}):
            prev = state["seen"][item.norm_url]
            reason = f"already in state file ({prev.get('status', 'seen')})"
        if reason:
            item.skip_reason = reason
            skipped.append(item)
            continue
        day = item.published.astimezone(tz).date().isoformat() if per_published_day and item.published else today
        already = int(posted_on.get(day) or 0) + used_on.get(day, 0)
        if already >= cap:
            item.skip_reason = f"daily cap reached ({cap}/day on {day})"
            skipped.append(item)
            continue
        accepted.append(item)
        used_on[day] = used_on.get(day, 0) + 1
        seen_this_run.add(item.url, item.title, f"earlier item this run from {item.source_id}")
    return accepted, skipped


def print_report(
    accepted: list[Item],
    skipped: list[Item],
    notes: list[str],
    lookback_hours: int,
    dry_run: bool,
    now: datetime,
) -> None:
    mode = "DRY RUN" if dry_run else "POST"
    print(f"Android news bot — {mode}")
    print(f"Now: {format_pt(now)}  lookback: {lookback_hours}h")
    if notes:
        print("Feeds:")
        for note in notes:
            print(f"  - {note}")
    print()
    print(f"Would post ({len(accepted)}):" if dry_run else f"Posting ({len(accepted)}):")
    if not accepted:
        print("  (none)")
    for item in accepted:
        print(f"  -> !{item.community}  [{item.source_id}]  {format_pt(item.published)}")
        print(f"     {item.title}")
        print(f"     {item.url}")
    # Only show skipped items that fell inside the lookback, plus filter/dup hits in-window.
    interesting = [
        it
        for it in skipped
        if it.skip_reason
        and not (it.skip_reason.startswith("older than lookback") or it.skip_reason == "no published date")
    ]
    print()
    print(f"Skipped in-window ({len(interesting)}):")
    if not interesting:
        print("  (none)")
    for item in interesting:
        print(f"  - [{item.source_id}] {item.title}")
        print(f"    {item.skip_reason}")
        print(f"    {item.url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post Android news to lemdro.id")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--state", default=None, help="Override state file path")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Print actions only (default)")
    parser.add_argument("--post", action="store_true", help="Actually post (requires ANDROIDNEWS_PASSWORD)")
    parser.add_argument("--lookback-hours", type=int, default=None)
    parser.add_argument("--jwt-file", default=None, help="Optional JWT file for read-only Lemmy calls in dry-run")
    args = parser.parse_args(argv)

    dry_run = not args.post
    config_path = Path(args.config).expanduser()
    config = yaml.safe_load(config_path.read_text())
    state_path = Path(args.state).expanduser() if args.state else (config_path.parent / (config.get("state_file") or "state.json"))
    if not state_path.is_absolute():
        state_path = config_path.parent / state_path
    lookback = args.lookback_hours if args.lookback_hours is not None else int(config.get("lookback_hours") or 48)
    now = datetime.now(timezone.utc)

    jwt = None
    jwt_file = args.jwt_file
    if jwt_file:
        jwt = Path(jwt_file).read_text().strip()
    lemmy = Lemmy(config["api_base"], config["user_agent"], jwt=jwt)

    default_community = config.get("default_community") or "android"
    community_ids: dict[str, int] = {}
    try:
        community_ids[default_community] = lemmy.community_id(default_community)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not resolve !{default_community}: {exc}", file=sys.stderr)
        return 1

    recent = lemmy.recent_posts(
        community_ids[default_community],
        int(config.get("dedupe_lookback_hours") or 168),
        int(config.get("dedupe_max_pages") or 6),
    )
    index = build_index_from_community(recent)
    state = load_state(state_path)
    items, notes = collect_items(config, now)
    notes.append(f"scanned {len(recent)} recent !{default_community} posts for dedupe")
    accepted, skipped = select_posts(items, config, index, state, now, lookback, per_published_day=dry_run)
    print_report(accepted, skipped, notes, lookback, dry_run, now)

    if dry_run:
        return 0

    password = os.environ.get(config.get("password_env") or "ANDROIDNEWS_PASSWORD")
    if not password:
        print(f"Refusing to post: ${config.get('password_env') or 'ANDROIDNEWS_PASSWORD'} is not set", file=sys.stderr)
        return 2
    username = config.get("username") or "AndroidNews"
    lemmy.login(username, password)

    tz = ZoneInfo(config.get("day_timezone") or "America/Los_Angeles")
    today = now.astimezone(tz).date().isoformat()
    posted_today = int((state.setdefault("posted_on", {})).get(today) or 0)
    errors = 0
    for item in accepted:
        cid = community_ids.get(item.community)
        if cid is None:
            try:
                cid = lemmy.community_id(item.community)
                community_ids[item.community] = cid
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to resolve !{item.community}: {exc}", file=sys.stderr)
                errors += 1
                continue
        try:
            lemmy.create_post(cid, item.title, item.url)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to post {item.url}: {exc}", file=sys.stderr)
            errors += 1
            continue
        print(f"Posted to !{item.community}: {item.title}")
        state.setdefault("seen", {})[item.norm_url] = {
            "title": item.title,
            "source": item.source_id,
            "community": item.community,
            "status": "posted",
            "published": item.published.isoformat() if item.published else None,
            "posted_at": now.isoformat(),
        }
        posted_today += 1
        state.setdefault("posted_on", {})[today] = posted_today
    save_state(state_path, state)
    os.chmod(state_path, 0o600)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
