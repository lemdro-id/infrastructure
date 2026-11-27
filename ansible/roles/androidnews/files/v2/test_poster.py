#!/usr/bin/env python3
"""Unit tests for AndroidNews v2. Not installed by the Ansible role."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import poster

ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "config.yaml"
TASKS_PATH = ROOT.parents[1] / "tasks" / "main.yml"

HUMAN_ADDRESS = (
    "Google Play Will Force Solo App Developers to Publish Their Home "
    "Addresses Worldwide in 2027"
)
ENGADGET_ADDRESS = "Google will soon share Android developers' addresses publicly"
NINE_TO_FIVE_ADDRESS = (
    "Android app developers will have to publicly post address, phone number in 2027"
)
HUAWEI_A = "Jury reaches a trade-secrets verdict against Huawei"
HUAWEI_B = "Huawei trade secrets verdict orders the company to pay"
SAMSUNG_A = "Samsung is building a private AI cloud"
SAMSUNG_B = "Samsung private cloud will power Galaxy AI features"
S26_DEAL = "Samsung Galaxy S26 Ultra deal cuts the price"
S27_NEWS = "Galaxy S27 Ultra leak shows a new camera"
S26_HERE = "Samsung Galaxy S26 Ultra is here"
S27_HERE = "Samsung Galaxy S27 Ultra is here"


class ZeroSim:
    def score(self, a, b):
        return 0.0, "tok=0.00"


class HighSim:
    def score(self, a, b):
        return 0.91, "tok=0.91"


class PosterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = yaml.safe_load(CFG_PATH.read_text())
        poster.set_synonyms(self.cfg.get("synonyms"))
        self.now = datetime(2026, 11, 27, 10, 0, tzinfo=poster.PT).astimezone(timezone.utc)
        self.quiet = datetime(2026, 11, 27, 2, 0, tzinfo=poster.PT).astimezone(timezone.utc)
        self.clf = poster.Classifier(self.cfg)
        self._n = 0

    def item(self, title: str, outlet: str = "9to5", published: datetime | None = None,
             url: str | None = None) -> poster.Item:
        self._n += 1
        src = {
            "id": f"{outlet}-{self._n}",
            "name": outlet,
            "outlet": outlet,
            "official": False,
            "role": "post",
            "priority": 2,
        }
        it = poster.make_item(
            src, title, url or f"https://example.com/{outlet}/{self._n}",
            published or (self.now - timedelta(hours=4)),
        )
        self.clf.classify(it)
        return it

    def cluster(self, items: list[poster.Item]) -> poster.Cluster:
        cl = poster.Cluster(items=items)
        poster.score_cluster(cl, self.cfg, self.now)
        return cl

    def record(self, title: str, by: str = "Mustachius_Grumpius", post_id: int = 1,
               url: str = "https://discuss.example/post/1") -> dict:
        return {
            "id": post_id,
            "title": title,
            "norm_url": url,
            "cluster_urls": [url],
            "toks": poster.tokens(title),
            "strong": [],
            "weak": [],
            "evs": [],
            "primary_links": [],
            "when": self.now.isoformat(),
            "by": by,
        }

    def v2_posts(self, n: int, hours_ago: float = 3, now: datetime | None = None) -> list[dict]:
        when = (now or self.now) - timedelta(hours=hours_ago)
        posts = []
        for i in range(n):
            url = f"https://example.com/posted/{hours_ago}-{i}"
            posts.append({
                "title": f"Ocean bulletin {i}",
                "url": url,
                "norm_url": url,
                "cluster_urls": [url],
                "toks": ["ocean", "bulletin", str(i)],
                "strong": [],
                "weak": [],
                "evs": [],
                "primary_links": [],
                "posted_at": when.isoformat(),
                "when": when.isoformat(),
                "by": "AndroidNews(v2)",
                "source": "v2",
            })
        return posts

    def poll(self, items: list[poster.Item], posted: list[dict] | None = None,
             now: datetime | None = None, lemmy: list[dict] | None = None):
        now = now or self.now
        sim = poster.prepare(items, self.cfg)
        state = {"version": 2, "posted": posted or [], "first_seen": {}}
        return poster.decide(items, self.cfg, state, lemmy or [], now, sim, resolve_primary=False)

    def explain(self, clusters, to_post) -> str:
        lines = [f"to_post={len(to_post)}"]
        for cl in clusters:
            title = cl.items[0].title[:70]
            lines.append(
                f"  score={cl.score} outlets={cl.outlets} flags={sorted(cl.flags)} "
                f"decision={cl.decision!r} skip={cl.skip!r} :: {title}"
            )
        return "\n".join(lines)


class RareStemTests(PosterTestCase):
    def test_generic_product_words_are_not_rare(self) -> None:
        for word in ("galaxy", "ultra", "pixel", "android", "google", "samsung",
                     "phone", "app", "update"):
            self.assertEqual(poster.rare_stems(word), set(), word)

    def test_c116_developer_address_vs_post_49105683(self) -> None:
        # Old URL/Jaccard/sim checks missed this human post. Rare stems catch it.
        self.assertLess(poster.title_jaccard(HUMAN_ADDRESS, ENGADGET_ADDRESS), 0.4)
        self.assertLess(poster.title_jaccard(HUMAN_ADDRESS, NINE_TO_FIVE_ADDRESS), 0.4)
        self.assertAlmostEqual(poster.title_jaccard(HUMAN_ADDRESS, ENGADGET_ADDRESS), 0.21, places=2)
        self.assertAlmostEqual(poster.title_jaccard(HUMAN_ADDRESS, NINE_TO_FIVE_ADDRESS), 0.27, places=2)

        for other in (ENGADGET_ADDRESS, NINE_TO_FIVE_ADDRESS):
            shared = poster.rare_stem_overlap(HUMAN_ADDRESS, other)
            self.assertIn("developer", shared)
            self.assertIn("address", shared)

        cl = poster.Cluster(items=[
            self.item(ENGADGET_ADDRESS, "yahoo", url="https://engadget.example/devs"),
            self.item(NINE_TO_FIVE_ADDRESS, "9to5", url="https://9to5.example/devs"),
        ])
        human = self.record(HUMAN_ADDRESS, by="Mustachius_Grumpius", post_id=49105683,
                            url="https://lemdro.example/post/49105683")
        hit = poster.community_hit(cl, [human], ZeroSim(), 0.5, 0.8)
        self.assertIn("49105683", hit)
        self.assertIn("rare stems", hit)
        self.assertIn("developer", hit)
        self.assertIn("address", hit)
        self.assertIn("Mustachius_Grumpius", hit)
        self.assertNotIn("same link", hit)

        bot = self.record(HUMAN_ADDRESS, by="AndroidNews", post_id=49109999,
                          url="https://lemdro.example/post/49109999")
        bot_hit = poster.community_hit(cl, [bot], ZeroSim(), 0.5, 0.8)
        self.assertIn("rare stems", bot_hit)
        self.assertIn("AndroidNews", bot_hit)

        to_post, clusters = self.poll(
            cl.items, lemmy=[human],
        )
        self.assertEqual(to_post, [])
        self.assertTrue(any(c.skip and "49105683" in c.skip for c in clusters),
                        self.explain(clusters, to_post))

    def test_huawei_trade_secrets_and_samsung_private_cloud_self_dups(self) -> None:
        huawei = poster.rare_stem_overlap(HUAWEI_A, HUAWEI_B)
        self.assertIn("trad", huawei)
        self.assertIn("secret", huawei)
        samsung = poster.rare_stem_overlap(SAMSUNG_A, SAMSUNG_B)
        self.assertIn("privat", samsung)
        self.assertIn("cloud", samsung)

        posted = self.record(HUAWEI_A, by="AndroidNews(v2)",
                             url="https://news.example/huawei-a")
        incoming = poster.Cluster(items=[
            self.item(HUAWEI_B, "authority-media", url="https://news.example/huawei-b"),
        ])
        hit = poster.dedupe_hit(incoming, [posted], ZeroSim(), 0.5, "we posted")
        self.assertIn("rare stems", hit)
        self.assertIn("trad", hit)
        self.assertIn("secret", hit)

        posted = self.record(SAMSUNG_A, by="AndroidNews(v2)",
                             url="https://news.example/samsung-a")
        incoming = poster.Cluster(items=[
            self.item(SAMSUNG_B, "yahoo", url="https://news.example/samsung-b"),
        ])
        hit = poster.dedupe_hit(incoming, [posted], ZeroSim(), 0.5, "we posted")
        self.assertIn("rare stems", hit)
        self.assertIn("privat", hit)
        self.assertIn("cloud", hit)

    def test_s26_ultra_does_not_collapse_into_s27_ultra(self) -> None:
        self.assertEqual(poster.rare_stem_overlap(S26_DEAL, S27_NEWS), set())
        self.assertEqual(poster.rare_stem_overlap(S26_HERE, S27_HERE), set())
        cl = poster.Cluster(items=[self.item(S26_DEAL, "9to5", url="https://news.example/s26")])
        rec = self.record(S27_NEWS, url="https://news.example/s27")
        self.assertIsNone(poster.community_hit(cl, [rec], ZeroSim(), 0.5, 0.8))
        self.assertIsNone(poster.dedupe_hit(cl, [rec], ZeroSim(), 0.5, "we posted"))

    def test_rare_stem_count_rules(self) -> None:
        # 2 stems shorter than 5 do not match. 3 short stems do. 2 with one
        # stem of 5+ do. A single long stem does not.
        self.assertEqual(poster.rare_stem_overlap("Zinc neon wafer", "Zinc neon board"), set())
        self.assertEqual(
            poster.rare_stem_overlap("Zinc neon mica wafer", "Zinc neon mica board"),
            {"zinc", "neon", "mica"},
        )
        self.assertEqual(
            poster.rare_stem_overlap("Quark meson result", "Quark meson finding"),
            {"quark", "meson"},
        )
        self.assertEqual(
            poster.rare_stem_overlap("Quark result today", "Quark finding today"),
            set(),
        )

    def test_older_url_and_jaccard_checks_still_win(self) -> None:
        cl = poster.Cluster(items=[
            self.item("Zinc wafer spotted", "9to5", url="https://news.example/same"),
        ])
        same_link = self.record("Totally different headline about quark",
                                url="https://news.example/same")
        hit = poster.community_hit(cl, [same_link], ZeroSim(), 0.5, 0.8)
        self.assertIn("same link", hit)

        near = "Samsung launches Android 17 support for foldable phones today"
        cl = poster.Cluster(items=[self.item(near, "9to5", url="https://news.example/a")])
        copied = self.record(near + " extra", url="https://news.example/b")
        self.assertGreaterEqual(poster.title_jaccard(near, copied["title"]), 0.8)
        hit = poster.community_hit(cl, [copied], ZeroSim(), 0.5, 0.8)
        self.assertIn("title match", hit)

        cl = poster.Cluster(items=[self.item("Zinc wafer spotted", "9to5",
                                             url="https://news.example/c")])
        other = self.record("Opal board spotted", url="https://news.example/d")
        self.assertEqual(poster.rare_stem_overlap(cl.items[0].title, other["title"]), set())
        hit = poster.community_hit(cl, [other], HighSim(), 0.5, 0.8)
        self.assertIn("same story sim", hit)


class FramingTests(PosterTestCase):
    def flags(self, title: str) -> dict:
        return self.item(title).flags

    def bonus(self, title: str) -> set[str]:
        return set(self.item(title).bonus)

    def test_rumor_and_privacy_apply_from_any_title(self) -> None:
        clean = "Samsung launches Android 17 support"
        control = self.cluster([
            self.item(clean, "9to5"),
            self.item(clean, "yahoo"),
        ])
        hedged = self.cluster([
            self.item(clean, "9to5"),
            self.item("Samsung reportedly launches Android 17 support", "yahoo"),
        ])
        self.assertNotIn("rumor", control.flags)
        self.assertIn("rumor", hedged.flags)
        self.assertAlmostEqual(hedged.score, control.score - 2.5, places=2)

        three = [self.item(clean, outlet) for outlet in ("9to5", "yahoo", "conde-nast")]
        plain = self.cluster(three)
        privacy = self.cluster([
            self.item(clean, "9to5"),
            self.item(clean, "yahoo"),
            self.item("Privacy: Samsung launches Android 17 support", "conde-nast"),
        ])
        self.assertNotIn("privacy", plain.flags)
        self.assertIn("privacy", privacy.flags)
        self.assertAlmostEqual(privacy.score, plain.score + 3, places=2)

        # A minority deal headline still uses median framing, not any-title.
        mixed = self.cluster([
            self.item(clean, "9to5"),
            self.item(clean, "yahoo"),
            self.item(clean + " flash sale", "conde-nast"),
        ])
        self.assertNotIn("deal", mixed.flags)
        self.assertAlmostEqual(mixed.score, plain.score, places=2)

    def test_single_rumor_is_not_double_counted(self) -> None:
        cl = self.cluster([self.item("Samsung reportedly launches a new handset")])
        self.assertEqual(list(cl.flags), ["rumor"])
        # 1 outlet (+2) + launches (+1) + rumor (-2.5) + single-source extra (-2).
        self.assertAlmostEqual(cl.score, -1.5, places=2)

    def test_bare_hedges_and_month_may(self) -> None:
        rumors = [
            "Samsung may announce a foldable phone",
            "Samsung could announce a foldable phone",
            "Samsung might announce a foldable phone",
            "Samsung is cooking up a foldable phone",
            "Samsung said to launch a foldable phone",
            "Pixel foldable rumored for next year",
            "Pixel foldable tipped for next year",
        ]
        for title in rumors:
            self.assertIn("rumor", self.flags(title), title)
        months = [
            "Galaxy event in May 2026",
            "Galaxy event on May 15",
            "Samsung event this May",
            "Early May Pixel preview",
        ]
        for title in months:
            self.assertNotIn("rumor", self.flags(title), title)

    def test_regulatory_fine_only(self) -> None:
        for title in (
            "Pixel camera works fine after the patch",
            "Pixel camera fine-tune arrives",
            "Refine the Pixel camera",
        ):
            self.assertFalse(any("fine" in key for key in self.bonus(title)), title)
        hits = {
            "Google fined over Android licensing": "fined",
            "€500 million fine for Android": "€500 million fine",
            "antitrust fine hits Android makers": "antitrust fine",
            "Samsung faces a record fine": "faces a record fine",
            "A fine of €10 hits Android vendors": "fine of",
            "Record fines against Samsung": "fines against",
            "issued a fine on Android vendors": "issued a fine",
            "levied fines on an Android vendor": "levied fines",
            "$1,200 fine for an Android bug": "$1,200 fine",
        }
        for title, needle in hits.items():
            self.assertIn(needle, self.bonus(title), title)

    def test_developer_play_store_and_ai_training_keywords(self) -> None:
        expected = {
            "New developer address rules on Android": "developer address",
            "Android developer addresses go public": "developer addresses",
            "developer identity checks come to Android": "developer identity",
            "developer verification expands on Android": "developer verification",
            "Play Store policy update for Android": "play store policy",
            "Play Console requirements for Android apps": "play console requirements",
            "Play Store rules change on Android": "play store rules",
            "Play Console policy shift on Android": "play console policy",
            "Play Console rules for Android sideloading": "play console rules",
            "Samsung adds AI training controls": "ai training",
            "Android photos opt out of training": "opt out",
            "Android opt-out switch arrives": "opt-out",
            "Samsung bans data training": "data training",
        }
        for title, needle in expected.items():
            self.assertIn(needle, self.bonus(title), title)
        for title in (
            "Samsung adds AI training controls",
            "Android photos opt out of training",
            "Android opt-out switch arrives",
            "Samsung bans data training",
        ):
            self.assertIn("privacy", self.flags(title), title)

    def test_deal_phrases_and_hard_exclude(self) -> None:
        deals = [
            "Pixel flash sale cuts the price",
            "Samsung cuts the price of the tablet",
            "Samsung cuts price on buds",
            "lowest price of the year on this Pixel",
            "lowest-ever price on this Pixel",
            "Pixel buds are 20% off today",
            "today's deals on Pixel phones",
            "a great deal on Pixel phones",
        ]
        for title in deals:
            self.assertIn("deal", self.flags(title), title)
        for title in (
            "This Pixel is ideal for gaming",
            "Dealing with a Pixel battery bug",
            "100% official Pixel support",
        ):
            self.assertNotIn("deal", self.flags(title), title)

        self.assertIn("deal", self.cfg["scoring"]["hard_exclude"])
        to_post, clusters = self.poll([self.item("Pixel flash sale cuts the price")])
        self.assertEqual(to_post, [])
        self.assertTrue(clusters[0].skip.startswith("excluded (deal)"), clusters[0].skip)


class ScheduleTests(PosterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.assertFalse(poster.in_quiet_hours(self.now, self.cfg))
        self.assertTrue(poster.in_quiet_hours(self.quiet, self.cfg))
        sched = self.cfg["schedule"]
        scoring = self.cfg["scoring"]
        self.cap = int(sched["rolling_cap_24h"])
        self.hard = self.cap + int(sched["big_overflow"])
        self.reserved = int(sched["reserved_high_priority_slots"])
        self.assertEqual(self.cap, 8)
        self.assertEqual(self.hard, 10)
        self.assertEqual(self.reserved, 2)
        self.assertEqual(scoring["high_priority_min_score"], 4.0)
        self.assertEqual(scoring["cap_bypass_min_outlets"], 2)

    def low_score(self, hours: float = 3) -> poster.Item:
        return self.item("Motorola launches a new handset", "motorola",
                         published=self.now - timedelta(hours=hours))

    def high_score(self, hours: float = 10, outlet: str = "9to5") -> poster.Item:
        return self.item("Samsung launches Android 17 support", outlet,
                         published=self.now - timedelta(hours=hours))

    def two_outlet(self, title: str, outlets: tuple[str, str], hours: float = 4) -> list[poster.Item]:
        when = self.now - timedelta(hours=hours)
        return [self.item(title, outlet, published=when) for outlet in outlets]

    def privacy_story(self) -> poster.Item:
        # Score stays under 4: one outlet (+2), privacy (+3), Gemini ai_feature (-2).
        return self.item("Samsung privacy tool for Gemini", "samsung",
                         published=self.now - timedelta(hours=10))

    def test_slot_six_still_accepts_a_low_score_story(self) -> None:
        to_post, clusters = self.poll([self.low_score()], self.v2_posts(self.cap - self.reserved - 1))
        self.assertEqual(len(to_post), 1, self.explain(clusters, to_post))
        self.assertNotIn("reserved", to_post[0].decision)
        self.assertLess(to_post[0].score, 4)

    def test_reserved_slots_7_and_8(self) -> None:
        for filled in (self.cap - self.reserved, self.cap - 1):  # 6 and 7 → slots 7 and 8
            low = self.low_score(3)
            high = self.high_score(10)
            to_post, clusters = self.poll([low, high], self.v2_posts(filled))
            self.assertEqual(len(to_post), 1, self.explain(clusters, to_post))
            self.assertGreaterEqual(to_post[0].score, 4)
            self.assertIn("reserved slot", to_post[0].decision)
            skipped = [c for c in clusters if c.skip]
            self.assertTrue(any("reserved high-priority" in (c.skip or "") for c in skipped),
                            self.explain(clusters, to_post))

            only_low, low_clusters = self.poll([self.low_score()], self.v2_posts(filled))
            self.assertEqual(only_low, [], self.explain(low_clusters, only_low))
            self.assertIn("reserved high-priority", low_clusters[0].skip)

    def test_privacy_flag_can_take_a_reserved_slot_below_score_4(self) -> None:
        low = self.low_score(3)
        privacy = self.privacy_story()
        to_post, clusters = self.poll([low, privacy], self.v2_posts(self.cap - 1))
        self.assertEqual(len(to_post), 1, self.explain(clusters, to_post))
        self.assertIn("privacy", to_post[0].flags)
        self.assertLess(to_post[0].score, 4)
        self.assertIn("reserved slot", to_post[0].decision)

    def test_two_outlet_score_bypasses_rolling_cap_until_hard_cap(self) -> None:
        pair = self.two_outlet("Samsung launches Android 17 support", ("9to5", "yahoo"))
        for filled in (self.cap, self.hard - 1):  # 8 and 9
            to_post, clusters = self.poll(pair, self.v2_posts(filled))
            self.assertEqual(len(to_post), 1, self.explain(clusters, to_post))
            self.assertGreaterEqual(to_post[0].score, 4)
            self.assertGreaterEqual(len(to_post[0].outlets), 2)
            self.assertIn("cap bypass", to_post[0].decision)
            self.assertNotIn("BIG", to_post[0].decision)

        blocked, clusters = self.poll(pair, self.v2_posts(self.hard))
        self.assertEqual(blocked, [], self.explain(clusters, blocked))
        self.assertIn(f"hard cap {self.hard}/24h", clusters[0].skip)

    def test_bypass_requires_two_outlets_and_score_4(self) -> None:
        one = [self.high_score(4)]
        to_post, clusters = self.poll(one, self.v2_posts(self.cap))
        self.assertEqual(to_post, [], self.explain(clusters, to_post))
        self.assertIn(f"rolling cap {self.cap}/24h", clusters[0].skip)

        weak = self.two_outlet("Samsung phone review covers the camera", ("9to5", "yahoo"))
        to_post, clusters = self.poll(weak, self.v2_posts(self.cap))
        self.assertEqual(to_post, [], self.explain(clusters, to_post))
        self.assertLess(clusters[0].score, 4)
        self.assertGreaterEqual(len(clusters[0].outlets), 2)
        self.assertIn(f"rolling cap {self.cap}/24h", clusters[0].skip)

    def test_big_stories_still_use_the_overflow_and_stop_at_10(self) -> None:
        big = self.two_outlet(
            "Samsung launches Android 17 support", ("9to5", "yahoo", "conde-nast"))
        ordinary = [self.low_score(4)]
        to_post, clusters = self.poll(big + ordinary, self.v2_posts(self.cap))
        self.assertEqual(len(to_post), 1, self.explain(clusters, to_post))
        self.assertTrue(to_post[0].big)
        self.assertIn("POST (big)", to_post[0].decision)
        queued = [c for c in clusters if c.skip and "big story posted this poll" in c.skip]
        self.assertEqual(len(queued), 1, self.explain(clusters, to_post))

        blocked, clusters = self.poll(big, self.v2_posts(self.hard))
        self.assertEqual(blocked, [], self.explain(clusters, blocked))
        self.assertIn(f"hard cap {self.hard}/24h", clusters[0].skip)

    def test_min_gap_quiet_hours_and_one_ordinary_post_still_hold(self) -> None:
        pair = self.two_outlet("Samsung launches Android 17 support", ("9to5", "yahoo"))
        gapped, clusters = self.poll(pair, self.v2_posts(self.cap, hours_ago=0.5))
        self.assertEqual(gapped, [], self.explain(clusters, gapped))
        self.assertIn("min gap", clusters[0].skip)

        q_when = self.quiet - timedelta(hours=4)
        pair_q = [
            self.item("Samsung launches Android 17 support", outlet, published=q_when)
            for outlet in ("9to5", "yahoo")
        ]
        quiet, clusters = self.poll(pair_q, self.v2_posts(self.cap, now=self.quiet), now=self.quiet)
        self.assertEqual(quiet, [], self.explain(clusters, quiet))
        self.assertIn("quiet hours", clusters[0].skip)

        other = self.two_outlet(
            "Huawei antitrust lawsuit ruling shakes the industry", ("gsmarena", "phonearena"))
        to_post, clusters = self.poll(pair + other, self.v2_posts(self.cap))
        self.assertEqual(len(to_post), 1, self.explain(clusters, to_post))
        self.assertIn("cap bypass", to_post[0].decision)
        waiting = [c for c in clusters if c.skip and "one ordinary post per poll" in c.skip]
        self.assertEqual(len(waiting), 1, self.explain(clusters, to_post))


class ConfigTests(PosterTestCase):
    def test_feed_urls_from_the_2026_11_27_audit(self) -> None:
        by_id = {s["id"]: s for s in self.cfg["sources"]}
        self.assertEqual(
            by_id["keyword-android"]["url"],
            "https://blog.google/products-and-platforms/platforms/android/rss/",
        )
        self.assertEqual(
            by_id["keyword-devices"]["url"],
            "https://blog.google/products-and-platforms/devices/rss/",
        )
        self.assertEqual(by_id["keyword-devices"]["stale_hours"], 336)
        self.assertEqual(
            by_id["android-developers"]["url"],
            "https://developer.android.com/static/blog/atom.xml",
        )
        lineage = by_id["lineageos"]
        self.assertEqual(lineage["url"], "https://lineageos.org/feed.xml")
        self.assertEqual(lineage["stale_hours"], 720)
        self.assertTrue(lineage["official"])
        self.assertTrue(lineage["enabled"])
        self.assertEqual(sum(1 for s in self.cfg["sources"] if s.get("enabled", True)), 20)

    def test_role_installs_an_explicit_file_list(self) -> None:
        tasks = yaml.safe_load(TASKS_PATH.read_text())
        v2 = next(
            task for task in tasks
            if isinstance(task.get("ansible.builtin.copy"), dict)
            and task["ansible.builtin.copy"].get("src") == "v2/{{ item }}"
        )
        self.assertEqual(v2["loop"], ["poster.py", "config.yaml", "README.md"])
        self.assertNotIn("test_poster.py", v2["loop"])


if __name__ == "__main__":
    unittest.main()
