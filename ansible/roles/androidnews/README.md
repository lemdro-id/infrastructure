# AndroidNews v2 (lemdro.id !android)

This bot posts Android news headlines and links to `!android` throughout the day, as stories become important. It uses each original headline and link only, with no generated summaries (the same rule as v1).

v1 posted its 5/day cap right after the 00:00 PT reset, oldest candidates first. That meant it posted 1–2-day-old stories in one burst and then went quiet. See `replay.md`.

## What it does each poll (cron every 15 min)

1. **Fetch** 20 feeds (`config.yaml → sources`): official Google, Android Developers, Samsung Newsroom and the security bulletins, plus news outlets. Each source has:
   - `outlet`: the owner group. Same owner counts as one outlet: Android Police and XDA are both Valnet.
   - `role`: `post` (may be the linked source) or `corroborate` (only counts toward coverage).
2. **Classify** each article:
   - Relevance (the include regexes; Samsung Newsroom has its own mobile filter).
   - Keyword bonuses.
   - Penalty categories: deal, sponsored, how-to, opinion/first-person, listicle, roundup/poll, rumor, review.
3. **Cluster** the same story across feeds with layered matching. The time window is 6 h, or 36 h for layer 1.
   1. *Shared primary link.* Two articles that link the same official page (blog.google, developer.android.com, news.samsung.com, source.android.com, …), or where one article *is* the other's cited source, are the same story. A small headline-overlap floor guards against old background links.
   2. *Entity Jaccard.* Product lines and versions are extracted ("Galaxy Z Fold 8", "Razr Flex", "One UI 9.5", "Android 17 QPR2", model codes like S26 or Raptor27), plus named apps and services and numbers. Company names alone are ignored, and sharing only an app name counts half.
   3. *IDF-weighted headline cosine.* Headline filler is removed as stopwords, and a tiny stemmer plus a `synonyms` map are applied (e.g. "app verification" = "sideloading").
   - **Launch-day guard:** if two headlines share a product or version but share little else, they are *different* stories unless both are the same event type (release, announce, security, price, leak, kill, legal). For example, "One UI 9.5 beta is rolling out" stays separate from "One UI 9.5 adds app lock".
   - A deal headline and a news headline about the same phone get a penalty, so they don't merge.
4. **Score** each cluster:
   - 2.0 per independent outlet.
   - +2.0 if an official source is in it.
   - +1 per keyword class, max +2.
   - Plus the penalties of the median article's framing.
   - −1 per recent post on the same product in the last 24 h (topic fatigue, max −2; big stories are exempt).
   - **Big** = 3 or more independent outlets and a score of 6 or more. Rumors and how-tos are never big. Deals and sponsored posts are never posted at all.
5. **Dedupe (48 h):**
   - By normalized URL and by story similarity.
   - Against our own posts (`state-v2.json`, plus AndroidNews's posts read back from Lemmy).
   - Against every recent `!android` post, so we never repost what a human already shared.
6. **Schedule:**
   - Big stories post on this poll, any time of day.
   - Ordinary stories wait 30 min to collect other outlets, then go to a queue that drains **one post at a time, best first**, with at least **90 min** between posts.
   - No ordinary posts 00:00–06:00 PT.
   - Rolling cap of **8 per 24 h** (not reset at midnight). Big stories may go to 10.
   - Stories go stale 12 h after their newest article.
   - **Fill mode:** after 4 h without any post (outside quiet hours), clean single-outlet stories (score 2 or more, no penalties) may post.
7. **Link choice:**
   - First, the official post, preferring the one most cited by the outlets in the cluster. This includes an official-feed post that outlets link to.
   - Then a primary page cited by 2 or more outlets, if its title can be read.
   - Otherwise, the most "central" clean headline from a preferred outlet, earliest first.

Every poll logs each cluster's score breakdown and why it was posted, queued, or skipped. Use `-v` to see all clusters.

## Files

This document is the README for Ansible role `androidnews` in `lemdro-id/infrastructure` (`ansible/roles/androidnews`) and is also installed at `/opt/android-news-bot/v2/README.md`.

| path | what |
|---|---|
| `files/poster.py`, `files/config.yaml`, `files/run.sh`, `files/README.md` | v1, still installed under `/opt/android-news-bot/` for rollback. Uses the stdlib plus PyYAML and python-dateutil. |
| `files/v2/poster.py`, `files/v2/config.yaml`, `files/v2/run.sh`, `files/v2/README.md` | v2, installed under `/opt/android-news-bot/v2/`. Same Python dependencies as v1; no new packages. |
| `files/android-news-bot.cron` | `*/15` job pointing at `/opt/android-news-bot/v2/run.sh`. |
| `tasks/main.yml` | Creates the user and directories, installs v1 and v2, writes the password from the vault to `/opt/android-news-bot/.password`, and installs cron only when `lemdroid_start_services` is true. |
| `tools/replay.py` | Simulation and replay against cached or live feeds and the Lemmy API. It never posts. `--embed` adds an optional embedding-model comparison and needs `fastembed`; it is not a dependency of the bot. |
| `docs/replay.md` | Report: v1 measured from the server log versus v2 simulated, the cluster list, embedding side-by-side and feed health. |
| `worker/feed-proxy.js` | Cloudflare Worker `androidnews-feed-proxy` on workers.dev. Not deployed by Ansible. |

## Usage

```bash
python3 poster.py                 # dry run (default): prints decisions, writes nothing
python3 poster.py -v              # dry run, every cluster with its score and join reasons
python3 replay.py --hours 48 --poll 15 --offline        # re-run the simulation on feeds-live/
ANDROIDNEWS_PASSWORD=... python3 poster.py --post        # real posting (needs the env var; never printed)
```

## Deploy (Ansible role `androidnews`)

This role installs v1 under `/opt/android-news-bot/` (left in place for rollback) and v2 under `/opt/android-news-bot/v2/`, and points `/etc/cron.d/android-news-bot` at v2:

```
*/15 * * * * androidnews /opt/android-news-bot/v2/run.sh
```

`files/v2/run.sh` follows v1's wrapper: it `cd`s to `/opt/android-news-bot/v2`, takes a flock on `/opt/android-news-bot/v2/.lock`, reads `/opt/android-news-bot/.password` into `ANDROIDNEWS_PASSWORD` (never echoed), runs `poster.py --post`, and appends output to `/opt/android-news-bot/v2/poster.log`. The password file is created from the Ansible vault (`vault_androidnews_password`) and is never in git.

v2 has been live on lemdroid-ovh since 2026-11-20 13:21 CET (Europe/Berlin), with `fill_after_hours: 0`. Applying the role with `lemdroid_start_services=true` should match that layout. The cron job is installed only when that flag is set, so v1 and v2 never run together (that would double-post).

v2 starts with an empty `state-v2.json` (mode 600). That is safe: it reads AndroidNews's last 48 h of !android posts, so v1's posts count toward the rolling cap and the dedupe.

Watch `v2/poster.log`. A poll takes about 7–10 s; most of that is fetching feeds.

## Valnet feeds (Android Police and XDA)

Android Police and XDA (Valnet) block the OVH server IP `51.81.109.184`, so those two feeds are fetched via the allowlisted Worker `androidnews-feed-proxy` on workers.dev (`worker/feed-proxy.js`). Ansible does not deploy the Worker. It allows two paths (`/androidpolice` and `/xda`), caches for 10 minutes, and returns 404 for everything else. To undo, point the two `url` fields in `files/v2/config.yaml` back at the sites (`https://www.androidpolice.com/feed/news/` and `https://www.xda-developers.com/feed/news/`) and delete the Worker.

## Roll back to v1

1. In `/etc/cron.d/android-news-bot`, restore the v1 line and remove the v2 line:

```
*/30 * * * * androidnews /opt/android-news-bot/run.sh
```

   On lemdroid-ovh a pre-cutover copy was also saved as `/root/android-news-bot.cron.bak-20261120`.

2. That's all. v1's `poster.py`, `config.yaml`, `state.json` and `run.sh` are left untouched by a v2 deploy.

   v1 doesn't read Lemmy for its cap. On the day of the rollback it may post up to 5 more, but its URL dedupe against !android stops reposts.

## Tuning notes

- The over-merge and under-merge knobs are in `clustering`:
  - `threshold` (0.42)
  - `tok_min` (0.18)
  - `tok_alone` (0.55)
  - `resid_min` (0.12), `guard_tok_max` (0.5)
  - `event_bonus`
- Re-run `replay.py` after changes and read the cluster list in `replay.md`.
- Add `synonyms` when outlets word the same topic differently.
- Embedding comparison (bge-small, cosine 0.84) on 328 articles: 83 same-story pairs layered, 74 by embedding, 59 shared.
  - Embeddings mostly add deal-to-deal merges, which don't matter because deals are excluded, and catch a few rewordings.
  - The layered matcher catches link-based merges that embeddings miss.
  - Embeddings are not needed for the bot.
