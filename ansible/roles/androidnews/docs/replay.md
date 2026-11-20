# AndroidNews v2: replay and simulation report

Generated 2026-11-20 around 12:10 CET (Europe/Berlin). This was a dry run only: nothing was posted, and the server was not touched.
Times are shown in US Pacific, which the bot's schedule logic uses, and in Berlin time.

## TL;DR

- **v1's real behaviour** (server `poster.log`, 197 runs, 15 Nov 22:00 PST to 20 Nov 02:30 PST): it made 25 posts. On every full day, all 5 posts went out in a single run right after the PT day reset: 00:00 PT (09:00 CET), or 02:00 PT on 19 Nov. After that it went silent. 90 different stories were skipped with "daily cap reached".
  The bigger problem is that v1 posts the **oldest** candidate first, so it was working through a 2-day backlog. In `state.json`, the median lag from article publication to the post is **28 h**. On 19 and 20 Nov every post was **44–47 h old**. For example, "Breaking: One UI 9.5 beta is rolling out…" went up 47 h after it broke.
- **v2 in the same 48 h, simulated with 15-min polls:** 15 posts, spread between 05:45 and 22:00 PT. The median lag after the first outlet reported a story is **about 2.5 h**, and big stories went up on the first poll after they crossed the threshold.
  Two posts linked the official source over the outlets: the Samsung Newsroom post for One UI 9.5, and Android Developers for the Play quality standards. v2 would have posted the Android developer verification announcement 30 min after Google published it. A human posted it about 21 h later.
- Two stories were held back because a human had already posted them on !android: WhatsApp backup and Galaxy Buds Active. A third, Samsung leadership, was held back later in the window.
- **Feeds:** all 20 v2 feeds fetch fine. Two official Google Keyword feeds are just quiet, not broken: Pixel's newest item is from 10 Nov and Wear OS's from 16 Jun. The new `/products-and-platforms/platforms/wear-os/rss/` path returns the same stale content. Reuters and AP have no public RSS, so they aren't included.

## How the simulation works (and its limits)

- Feeds were fetched once (`feeds-live/`, 20 Nov ~11:56 CET). The run then stepped through the last 48 h in 15-minute polls. At each poll v2 only "sees" items whose published time is at or before that poll. Dedupe uses the human (non-AndroidNews) posts that existed on !android at that moment, taken from the live Lemmy API.
- Limits: short feeds don't reach back 48 h. Android Police, XDA, Engadget and The Verge only carry 10–20 items, and GSMArena, XDA, Engadget and Android Headlines begin mid-window (see the coverage table). Day 1 therefore undercounts outlets. Articles a feed has already dropped are invisible. IDF weights come from the whole snapshot (a tiny look-ahead).
- v1's numbers are **real** (from the server log). v2's numbers are **simulated**.

## v1 measured from the live server log

| date (PT) | v1 posts and run time | lag (published → posted) |
|---|---|---|
| Sun 15 Nov | 2 at 21:51 (manual run) | 0.7–2.8 h |
| Mon 16 Nov | 5 between 01:00 and 08:30 (first day; items arrived one by one) | 0.1–0.4 h |
| Tue 17 Nov | 5, all at 00:00 | 12–15 h |
| Wed 18 Nov | 5, all at 00:00 | 26–33 h |
| Thu 19 Nov | 5, all at 02:00 (10:00 UTC; first runs after the OVH move) | 44–47 h |
| Fri 20 Nov | 5, all at 00:00 | 45–47 h |

Skip reasons across all runs: title filter 5,460, not Android-related 5,418, **daily cap reached 5,401** (90 unique stories), duplicate URL 1,495. There was 1 fetch failure ("Network is unreachable", one run).

## v2 simulation: last 48 h, 15-min polls

Window: Wed 11-18 03:00 PST / 12:00 CET → Fri 11-20 03:00 PST / 12:00 CET  (48h, poll every 15 min, 193 polls)

### Feed coverage in this snapshot

| feed | status | items | oldest item | newest item |
|---|---|---|---|---|
| keyword-android | ok | 20 | Tue 06-16 11:00 PDT | Wed 11-18 09:00 PST |
| keyword-pixel | stale (newest Tue 11-10 11:00 PST) | 20 | Wed 08-12 07:00 PDT | Tue 11-10 11:00 PST |
| keyword-wear | stale (newest Tue 06-16 11:00 PDT) | 20 | Thu 01-14 08:00 PST | Tue 06-16 11:00 PDT |
| android-developers | ok | 20 | Sun 10-11 17:00 PDT | Wed 11-18 16:00 PST |
| samsung-newsroom | ok | 50 | Mon 09-14 15:10 PDT | Fri 11-20 01:01 PST |
| asb | ok | 2 | Sun 10-04 17:00 PDT | Sun 11-01 16:00 PST |
| pixel-bulletin | ok | 2 | Mon 10-05 17:00 PDT | Mon 11-09 16:00 PST |
| 9to5google | ok | 100 | Fri 11-13 14:00 PST | Thu 11-19 17:35 PST |
| androidauthority-news | ok | 80 | Tue 11-17 14:01 PST | Fri 11-20 02:31 PST |
| androidpolice-news | ok | 10 | Wed 11-18 11:12 PST | Thu 11-19 22:09 PST |
| verge-google | ok | 10 | Thu 11-12 09:00 PST | Thu 11-19 12:05 PST |
| verge-android | ok | 10 | Thu 10-15 05:00 PDT | Thu 11-19 10:19 PST |
| arstechnica-gadgets | ok | 20 | Tue 11-10 14:35 PST | Thu 11-19 14:16 PST |
| gsmarena | ok | 20 | Thu 11-19 03:02 PST | Fri 11-20 02:11 PST |
| androidcentral | ok | 50 | Fri 11-13 08:00 PST | Fri 11-20 01:05 PST |
| droidlife | ok | 15 | Tue 11-17 10:48 PST | Thu 11-19 16:32 PST |
| xda-news | ok | 10 | Thu 11-19 08:39 PST | Thu 11-19 22:22 PST |
| engadget | ok | 20 | Thu 11-19 09:01 PST | Thu 11-19 23:31 PST |
| phonearena | ok | 50 | Wed 11-18 17:15 PST | Fri 11-20 01:59 PST |
| androidheadlines | ok | 35 | Thu 11-19 06:53 PST | Thu 11-19 16:03 PST |

### v2 would post (15)

| # | posted (PT / Berlin) | score | type | lag after first outlet report | outlets | headline (linked source) |
|---|---|---|---|---|---|---|
| 1 | Wed 11-18 05:45 PST / 14:45 CET | 8 | **BIG** | 7h44m | 3 | Samsung Begins One UI 9.5 Beta Program (news.samsung.com) |
| 2 | Wed 11-18 07:15 PST / 16:15 CET | 6 | ordinary | 1h15m | 2 | AAWireless releases new, smaller Nexus and Nano wireless Android Auto adapters (9to5google.com) |
| 3 | Wed 11-18 08:45 PST / 17:45 CET | 4 | ordinary | 5h22m | 2 | Google Wallet is preparing digital Social Security cards that show your benefits (androidauthority.com) |
| 4 | Wed 11-18 10:15 PST / 19:15 CET | 8 | **BIG** | 0h15m | 3 +official | Elevating apps: New adaptive quality standards on Google Play (developer.android.com) |
| 5 | Wed 11-18 11:45 PST / 20:45 CET | 3 | ordinary | 2h45m | 0 +official | The Gemini app is now available on lower-memory Android devices. (blog.google) |
| 6 | Wed 11-18 13:15 PST / 22:15 CET | 3 | ordinary | 0h58m | 1 | Motorola Razr Fold receives its first major OS upgrade with Android 17 (androidauthority.com) |
| 7 | Wed 11-18 14:45 PST / 23:45 CET | 3 | ordinary | 1h25m | 1 | Google Pixel officially re-releases App Lock in beta, Samsung Galaxy gets it too (9to5google.com) |
| 8 | Wed 11-18 16:30 PST / 01:30 CET | 3 | ordinary | 0h30m | 0 +official | Expanding Android developer verification in 2027 (developer.android.com) |
| 9 | Thu 11-19 06:00 PST / 15:00 CET | 4 | ordinary | 2h27m | 1 | One UI 9.5 beta quietly kills Audio Brief and Moments in Now Brief (androidauthority.com) |
| 10 | Thu 11-19 07:30 PST / 16:30 CET | 4 | ordinary | 3h55m | 2 | Motorola's iPhone Duo rival is taking shape, and it could pack a surprise chipset (androidpolice.com) |
| 11 | Thu 11-19 09:00 PST / 18:00 CET | 4 | ordinary | 8h03m | 2 | GameNative just fixed PC gaming on Pixels and Exynos-powered Galaxy phones (androidauthority.com) |
| 12 | Thu 11-19 10:30 PST / 19:30 CET | 3 | ordinary | 9h29m | 1 | HONOR Watch 6 Pro goes global, but you’ll have to wait for one key feature (Updated) (androidauthority.com) |
| 13 | Thu 11-19 14:30 PST / 23:30 CET | 2 | ordinary | 2h48m | 1 | Honor just supercharged its smartwatch lineup with a new Pro model (9to5google.com) |
| 14 | Thu 11-19 18:30 PST / 03:30 CET | 2 | ordinary | 0h55m | 1 | Samsung’s mobile division has someone new in charge for the first time in years (9to5google.com) |
| 15 | Thu 11-19 22:00 PST / 07:00 CET | 4 | ordinary | 0h35m | 1 | Motorola details its Android 17 rollout plans for 29 phones (androidauthority.com) |

Score breakdowns:

1. 3 outlet(s) x2.0; keywords ['one ui 9.5', 'released', 'releases'] +2 — POST (big); queue behind it: 3
2. 2 outlet(s) x2.0; keywords ['releases', 'unveils'] +2 — POST (ordinary, rank 5.81); queue behind it: 0
3. 2 outlet(s) x2.0 — POST (ordinary, rank 3.19); queue behind it: 0
4. 3 outlet(s) x2.0; official +2.0 — POST (big); queue behind it: 1
5. 0 outlet(s) x2.0; official +2.0; keywords ['now available'] +1 — POST (ordinary, rank 2.59); queue behind it: 0
6. 1 outlet(s) x2.0; keywords ['android 17'] +1 — POST (ordinary, rank 2.85); queue behind it: 0
7. 1 outlet(s) x2.0; keywords ['releases'] +1 — POST (ordinary, rank 2.79); queue behind it: 0
8. 0 outlet(s) x2.0; official +2.0; keywords ['developer verification'] +1 — POST (ordinary, rank 2.92); queue behind it: 0
9. 1 outlet(s) x2.0; keywords ['kills', 'one ui 9.5'] +2 — POST (ordinary, rank 3.63); queue behind it: 10
10. 2 outlet(s) x2.0 — POST (ordinary, rank 3.41); queue behind it: 4
11. 2 outlet(s) x2.0 — POST (ordinary, rank 2.79); queue behind it: 3
12. 1 outlet(s) x2.0; keywords ['goes global'] +1 — POST (ordinary, rank 1.58); queue behind it: 0
13. 1 outlet(s) x2.0 — POST (ordinary, rank 1.58); queue behind it: 12
14. 1 outlet(s) x2.0 — POST (ordinary, rank 1.86); queue behind it: 13
15. 1 outlet(s) x2.0; keywords ['android 17', 'rollout'] +2 — POST (ordinary, rank 3.91); queue behind it: 0

### v1 actually posted in the same window (10, from server poster.log)

| posted (PT / Berlin) | headline |
|---|---|
| Thu 11-19 02:00 PST / 11:00 CET | Android Time Machine lets you try Android 2.1 through 7.1 right in your browser |
| Thu 11-19 02:00 PST / 11:00 CET | Banana Native now runs 10 Switch 2 games on Android, including Mario Kart World |
| Thu 11-19 02:00 PST / 11:00 CET | Samsung is testing agentic SmartThings features to run smarter automations, cut your energy bills |
| Thu 11-19 02:00 PST / 11:00 CET | XREAL Aura Initial Review: Taking Android XR out of the headset, but who is it for? |
| Thu 11-19 02:00 PST / 11:00 CET | Oppo may finally be fixing broken 3rd-party launchers with ColorOS 17 |
| Fri 11-20 00:00 PST / 09:00 CET | YouTube Music removes Samples tab from its bottom bar on Android and iOS |
| Fri 11-20 00:00 PST / 09:00 CET | Hokkaido is a Switch 2 emulator for Android that now also offers native ports |
| Fri 11-20 00:00 PST / 09:00 CET | Breaking: One UI 9.5 beta is rolling out to Galaxy S26 series right now |
| Fri 11-20 00:00 PST / 09:00 CET | Samsung brings native app lock to Galaxy phones with One UI 9.5 |
| Fri 11-20 00:00 PST / 09:00 CET | Here’s everything new in Samsung One UI 9.5 beta |

### Posts by hour of day (PT)

| hour PT | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1 | 5 |  | 5 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| v2 |  |  |  |  |  | 1 | 1 | 2 | 1 | 1 | 2 | 1 |  | 1 | 2 |  | 1 |  | 1 |  |  |  | 1 |  |

Overlap: 0 of v2's posts were also posted by v1 (same headline); 10 of v2's posts were items v1 saw but skipped with 'daily cap reached'.

### Stories v2 held back because a human had already posted them (3)

- Wed 11-18 03:00 PST / 12:00 CET score 3: WhatsApp starts rolling out built-in cloud backup on Android, and it’s free — same story (on !android: 'WhatsApp is rolling out a new cloud backup storage on Android' by Mustachius_Grumpius, sim 0.61 ent=0.50 tok=0.70 (headlines alone match))
- Thu 11-19 03:00 PST / 12:00 CET score 4: Galaxy Buds Active leak shows workout earbuds with ANC, ear hooks, IP68, and one odd omission — same story (on !android: 'Exclusive: Samsung Galaxy Buds Active Revealed With Ear Hooks, IP68 an' by Mustachius_Grumpius, sim 0.82 ent=1.00 tok=0.68 resid=0.54)
- Fri 11-20 01:15 PST / 10:15 CET score 3: Samsung Electronics Announces New Leadership — duplicate url (on !android: 'Samsung Electronics Announces New Leadership [Won-Joon Choi replaces T' by Mustachius_Grumpius Thu 11-19 21:46 PST)

### Clusters formed over the window (285 clusters, 24 with 2+ articles)

- **c065** score 10 BIG, 5 outlet(s): 5 outlet(s) x2.0
  - Wed 11-18 15:42 PST `9to5google` Google AI Ultra upgrade adds YouTube Premium Family  _(join: seed)_
  - Wed 11-18 17:44 PST `droidlife` I Might Switch to Google AI Ultra With This New YouTube Upgrade  _(join: 0.44 ent=0.25 tok=0.59 (headlines alone match))_
  - Wed 11-18 20:57 PST `androidpolice-news` Google AI Ultra plan brings ad-free YouTube to the whole family  _(join: 0.53 ent=0.50 tok=0.55 (headlines alone match))_
  - Wed 11-18 20:58 PST `androidauthority-news` Google AI Ultra now includes YouTube Premium Family at no extra cost  _(join: 0.53 ent=0.50 tok=0.56 (headlines alone match))_
  - Thu 11-19 02:12 PST `androidcentral` Google AI Ultra subscribers just got a free YouTube Premium Family upgrade  _(join: 0.47 ent=0.50 tok=0.44)_
- **c001** score 12 BIG, 4 outlet(s) +official: 4 outlet(s) x2.0; official +2.0; keywords ['one ui 9.5', 'released', 'releases'] +2
  - Tue 11-17 22:00 PST `androidauthority-news` Galaxy S26 owners could get their first taste of One UI 9.5 today  _(join: seed)_
  - Wed 11-18 01:05 PST `androidauthority-news` Breaking: One UI 9.5 beta is rolling out to Galaxy S26 series right now  _(join: 0.60 ent=0.64 tok=0.57 resid=0.00)_
  - Wed 11-18 01:47 PST `androidcentral` Samsung One UI 9.5 beta released for Galaxy S26: Here's what's new [Changelog]  _(join: 1.00 shared primary link (tok=0.85))_
  - Wed 11-18 02:33 PST `androidauthority-news` Here’s everything new in Samsung One UI 9.5 beta  _(join: 1.00 shared primary link (tok=0.58))_
  - Wed 11-18 05:45 PST `9to5google` Samsung releases its next major update, One UI 9.5, in beta for Galaxy S26 – what’s new  _(join: 1.02 ent=0.78 tok=1.00 resid=1.00 +event(release))_
  - Wed 11-18 08:33 PST `9to5google` One UI 9.5 Beta is out now for these Galaxy devices – how to install it  _(join: 0.55 ent=0.33 tok=0.51 resid=0.34 +event(release))_
  - Wed 11-18 10:00 PST `samsung-newsroom` Samsung Begins One UI 9.5 Beta Program  _(join: 1.00 shared primary link (tok=0.48))_
  - Wed 11-18 10:01 PST `droidlife` Samsung Opens One UI 9.5 Beta for Galaxy S26 Lineup  _(join: 0.90 ent=0.78 tok=0.78 resid=0.53 +event(release))_
- **c013** score 8 BIG, 4 outlet(s): 4 outlet(s) x2.0
  - Wed 11-18 03:22 PST `androidauthority-news` Google Wallet is preparing digital Social Security cards that show your benefits  _(join: seed)_
  - Wed 11-18 07:40 PST `9to5google` Google Wallet may soon be able to store your Social Security card  _(join: 0.44 ent=0.50 tok=0.38)_
  - Wed 11-18 11:30 PST `androidcentral` A digital Social Security card? It has me skeptical, but Google Wallet might do it  _(join: 0.47 ent=0.50 tok=0.45)_
  - Wed 11-18 12:58 PST `androidpolice-news` Google Wallet may soon store your Social Security card and federal benefits  _(join: 0.54 ent=0.50 tok=0.57 (headlines alone match))_
- **c039** score 8 BIG, 4 outlet(s): 4 outlet(s) x2.0
  - Wed 11-18 10:00 PST `9to5google` Google Play wants Android apps to nail foldable basics by April 2027  _(join: 1.00 shared primary link (tok=0.18))_
  - Wed 11-18 10:00 PST `verge-google` Google is forcing Android app developers to properly support foldables  _(join: 1.00 shared primary link (tok=0.11))_
  - Wed 11-18 10:00 PST `verge-android` Google is forcing Android app developers to properly support foldables  _(join: 9.90 same url)_
  - Wed 11-18 10:00 PST `androidauthority-news` Google’s mandatory foldable app guidelines are here, and optimized apps are coming in 2027  _(join: 1.00 shared primary link (tok=0.16))_
  - Thu 11-19 02:15 PST `androidcentral` Your foldable phone deserves better, and Google is making developers deliver  _(join: 1.00 shared primary link (tok=0.13))_
- **c067** score 10 BIG, 3 outlet(s) +official: 3 outlet(s) x2.0; official +2.0; keywords ['developer verification', 'launch', 'sideloading'] +2
  - Wed 11-18 16:00 PST `android-developers` Expanding Android developer verification in 2027  _(join: seed)_
  - Thu 11-19 10:00 PST `arstechnica-gadgets` Google will launch Android app verification requirement globally in January 2027  _(join: 1.00 shared primary link (tok=0.52))_
  - Thu 11-19 10:00 PST `androidauthority-news` Android’s controversial sideloading rules go global in January  _(join: 0.44 ent=0.25 tok=0.59 (headlines alone match))_
  - Thu 11-19 16:41 PST `androidcentral` Android's sideloading freedom is about to get a lot more complicated worldwide  _(join: 1.00 shared primary link (tok=0.30))_
- **c194** score 6 BIG, 3 outlet(s): 3 outlet(s) x2.0
  - Thu 11-19 10:21 PST `verge-google` Gemini on Mac can now use your computer  _(join: seed)_
  - Thu 11-19 10:55 PST `9to5google` Gemini app for Mac adds computer use to control desktop apps  _(join: 1.00 shared primary link (tok=0.69))_
  - Thu 11-19 12:04 PST `androidauthority-news` Google brings computer use to Mac, letting Gemini handle chores without hijacking your screen  _(join: 1.00 shared primary link (tok=0.61))_
- **c104** score 4.5, 3 outlet(s): 3 outlet(s) x2.0; penalties rumor('leaks') -1.5
  - Thu 11-19 03:34 PST `androidpolice-news` Motorola's iPhone Duo rival is taking shape, and it could pack a surprise chipset  _(join: seed)_
  - Thu 11-19 06:50 PST `9to5google` Motorola Razr Flex leaks in real life with Fold 8 and iPhone Duo shape, mystery chipset  _(join: 0.46 ent=0.50 tok=0.43 resid=0.34)_
  - Thu 11-19 08:40 PST `9to5google` Motorola’s iPhone Duo competitor, Razr Flex, leaks in detailed images [Gallery]  _(join: 0.82 ent=1.00 tok=0.46 resid=0.19 +event(leak))_
  - Thu 11-19 11:56 PST `androidauthority-news` New Motorola Razr Flex renders offer best look yet at wide-body foldable  _(join: 0.47 ent=0.40 tok=0.30 resid=0.10 +event(leak))_
- **c030** score 1, 3 outlet(s): 3 outlet(s) x2.0; keywords ['price'] +1; penalties deal('Deals') -6
  - Wed 11-18 08:50 PST `9to5google` Deals: Pixel Watch 5 hits Black Friday price at $100 off, Galaxy Watch 9 $110 off, Galaxy Tabs $300 off, more  _(join: seed)_
  - Wed 11-18 11:44 PST `androidcentral` The Pixel Watch 5 is finally below $300 thanks to this early Black Friday deal  _(join: 0.44 ent=0.43 tok=0.45 resid=0.30)_
  - Wed 11-18 17:32 PST `phonearena` Your Pixel Watch 5 could last longer on runs, thanks to a Play services update  _(join: 0.45 ent=0.83 tok=0.35 -framing(deal vs news) resid=0.17)_
- **c020** score 6, 2 outlet(s): 2 outlet(s) x2.0; keywords ['releases', 'unveils'] +2
  - Wed 11-18 06:00 PST `9to5google` AAWireless releases new, smaller Nexus and Nano wireless Android Auto adapters  _(join: seed)_
  - Wed 11-18 06:00 PST `androidauthority-news` AAWireless unveils two new wireless Android Auto adapters with a big connectivity upgrade  _(join: 0.75 ent=1.00 tok=0.54 resid=0.46)_
- **c029** score 6, 2 outlet(s): 2 outlet(s) x2.0; keywords ['launch', 'rolling out'] +2
  - Wed 11-18 08:49 PST `9to5google` YouTube Music rolling out corner Gemini icon to launch Ask Music  _(join: seed)_
  - Wed 11-18 10:46 PST `androidauthority-news` YouTube Music is making Ask Music easier to access with a dedicated Gemini button  _(join: 0.57 ent=0.50 tok=0.63 (headlines alone match))_
- **c051** score 5, 2 outlet(s): 2 outlet(s) x2.0; keywords ['android 17'] +1
  - Wed 11-18 12:16 PST `androidauthority-news` Motorola Razr Fold receives its first major OS upgrade with Android 17  _(join: seed)_
  - Wed 11-18 13:35 PST `9to5google` Motorola Razr Fold finally gets its Android 17 update – hopefully the next 7 years go faster  _(join: 0.69 ent=1.00 tok=0.44 resid=0.14)_
- **c058** score 5, 2 outlet(s): 2 outlet(s) x2.0; keywords ['launches'] +1
  - Wed 11-18 13:34 PST `9to5google` Google launches Gemini 4 Neon with Carbon quality at Flash speeds, live for AI Pro  _(join: seed)_
  - Wed 11-18 15:00 PST `androidauthority-news` Gemini 4 Neon is ready to get some work done for AI Pro power users  _(join: 1.00 shared primary link (tok=0.37))_
- **c074** score 4, 2 outlet(s): 2 outlet(s) x2.0
  - Wed 11-18 22:29 PST `androidauthority-news` Galaxy Buds Active leak shows workout earbuds with ANC, ear hooks, IP68, and one odd omission  _(join: seed)_
  - Thu 11-19 02:54 PST `phonearena` Samsung's Galaxy Buds Active could be great gym earbuds, with one catch  _(join: 0.47 ent=0.67 tok=0.32 resid=0.13)_
- **c087** score 4, 2 outlet(s): 2 outlet(s) x2.0
  - Thu 11-19 00:56 PST `androidauthority-news` GameNative just fixed PC gaming on Pixels and Exynos-powered Galaxy phones  _(join: seed)_
  - Thu 11-19 04:47 PST `androidpolice-news` GameNative's new update brings reliable PC gaming to Pixels and Samsung Exynos  _(join: 0.42 ent=0.00 tok=0.70 (headlines alone match))_
- **c157** score 4, 2 outlet(s): 2 outlet(s) x2.0
  - Thu 11-19 08:32 PST `androidauthority-news` Fitbit Edge owners are complaining about the lack of hourly movement reminders  _(join: seed)_
  - Thu 11-19 14:28 PST `androidheadlines` Fitbit Edge Owners Complain About the Missing Movement Reminders  _(join: 0.42 ent=0.00 tok=0.77 (headlines alone match))_
- **c229** score 4, 2 outlet(s): 2 outlet(s) x2.0
  - Thu 11-19 13:54 PST `androidheadlines` Instagram Finally Lets You Edit Stories After Posting Them  _(join: seed)_
  - Thu 11-19 17:02 PST `gsmarena` About time: You can now edit your Instagram Stories after posting them  _(join: 0.51 ent=0.00 tok=0.92 (headlines alone match))_
- **c076** score 2.5, 2 outlet(s): 2 outlet(s) x2.0; penalties rumor('leak') -1.5
  - Wed 11-18 23:11 PST `androidauthority-news` Major Galaxy Studio leak reveals battery size, headphone jack, and plenty more  _(join: seed)_
  - Thu 11-19 03:53 PST `androidcentral` Watch your back Sony, Samsung’s ‘Galaxy Studio’ headphones are on the way — and these major leaks show them in all their glory  _(join: 0.74 ent=1.00 tok=0.31 resid=0.20 +event(leak))_
- **c097** score 2.5, 2 outlet(s): 2 outlet(s) x2.0; penalties rumor('FCC') -1.5
  - Thu 11-19 02:48 PST `androidauthority-news` A mystery Motorola ‘Raptor27’ phone just cleared the FCC, and it looks like a 2027 Razr flip  _(join: seed)_
  - Thu 11-19 06:59 PST `androidheadlines` Motorola’s Mysterious ‘Raptor27’ Phone Just Hit the FCC, and It’s Not the Razr Flex  _(join: 0.52 ent=0.30 tok=0.49 resid=0.40 +event(leak))_
- **c112** score -1, 2 outlet(s): 2 outlet(s) x2.0; keywords ['price'] +1; penalties deal('Black Friday') -6
  - Thu 11-19 04:30 PST `9to5google` Galaxy Z Fold 8 is $1,499 for Black Friday; its new lowest price ever, just not for everyone  _(join: seed)_
  - Thu 11-19 07:11 PST `phonearena` Black Friday brings the Galaxy Z Fold 8 Ultra to an unmissable price  _(join: 0.66 ent=0.57 tok=0.52 resid=0.28 +event(price))_
- **c163** score -1, 2 outlet(s): 2 outlet(s) x2.0; keywords ['price'] +1; penalties deal('Price Cuts') -6
  - Thu 11-19 08:42 PST `droidlife` Pixel 11 Pro Gets Biggest Price Cuts to Date  _(join: seed)_
  - Thu 11-19 10:18 PST `androidcentral` Lowest we've seen it—Pixel 11 Pro XL gets a huge 31% Black Friday price knock that's too hard to ignore  _(join: 0.50 ent=0.57 tok=0.23 resid=0.08 +event(price))_
- **c195** score -2, 2 outlet(s): 2 outlet(s) x2.0; penalties deal('Black Friday') -6
  - Thu 11-19 10:23 PST `phonearena` Save a total of $600 with Samsung's top Galaxy S26 Ultra Black Friday deal while you can!  _(join: seed)_
  - Thu 11-19 12:43 PST `gsmarena` Amazon US Black Friday deal: the Galaxy S26 Ultra and Z Fold8 Ultra are both $350 off  _(join: 0.46 ent=0.60 tok=0.35 resid=0.16)_
- **c203** score -2, 2 outlet(s): 2 outlet(s) x2.0; penalties deal('Black Friday') -6
  - Thu 11-19 11:08 PST `androidheadlines` Best Black Friday Deals 2026 on Android Phones, Tablets and TVs  _(join: seed)_
  - Thu 11-19 14:31 PST `gsmarena` Amazon Black Friday Week: best tablet deals  _(join: 0.42 ent=0.00 tok=0.66 (headlines alone match))_
- **c103** score 4, 1 outlet(s): 1 outlet(s) x2.0; keywords ['kills', 'one ui 9.5'] +2
  - Thu 11-19 03:32 PST `androidauthority-news` One UI 9.5 beta quietly kills Audio Brief and Moments in Now Brief  _(join: seed)_
  - Thu 11-19 07:10 PST `androidauthority-news` One UI 9.5 could make booking an Uber part of your Now Brief routine  _(join: 0.50 ent=0.67 tok=0.36 resid=0.27)_
- **c047** score -0.5, 1 outlet(s): 1 outlet(s) x2.0; keywords ['one ui 9.5'] +1; penalties rumor('is building') -3.5
  - Wed 11-18 11:22 PST `androidauthority-news` Samsung is building a secure way for Galaxy users to erase their phones in One UI 9.5  _(join: seed)_
  - Wed 11-18 11:37 PST `androidauthority-news` One UI 9.5 could give lost phones a better chance of finding their way home with lock screen IMEI  _(join: 0.58 ent=1.00 tok=0.24 resid=0.14)_

### Side-by-side: local embedding model (bge-small-en-v1.5, cosine ≥ 0.84, same 6h greedy)

Unique articles: 328. Same-story pairs: layered=84, embedding=74, both=59. Embedding multi-article clusters: 21.

Pairs only the embedding model merged (first 25):

- 0.93 `phonearena` The Pixel 10 becomes the go-to choice for deal hunters thanks to Amazon’s Black Friday deal  ⟷  `phonearena` Pixel 10a becomes a real treat with Amazon’s Black Friday deal
- 0.87 `phonearena` Samsung outdoes Amazon with epic Galaxy Z Fold 8 Black Friday savings of up to $650 (sans trade-in)  ⟷  `9to5google` Galaxy Z Fold 8 is $1,499 for Black Friday; its new lowest price ever, just not for everyone
- 0.86 `9to5google` Best Black Friday deals now live: Google Pixel, Samsung, Amazon Echo, TVs, Anker, much more  ⟷  `androidheadlines` Best Black Friday Deals 2026 on Android Phones, Tablets and TVs
- 0.86 `phonearena` Samsung outdoes Amazon with epic Galaxy Z Fold 8 Black Friday savings of up to $650 (sans trade-in)  ⟷  `phonearena` Black Friday brings the Galaxy Z Fold 8 Ultra to an unmissable price
- 0.85 `phonearena` Black Friday brings the Galaxy Z Fold 8 Ultra to an unmissable price  ⟷  `gsmarena` Amazon US Black Friday deal: the Galaxy S26 Ultra and Z Fold8 Ultra are both $350 off
- 0.85 `phonearena` Samsung outdoes Amazon with epic Galaxy Z Fold 8 Black Friday savings of up to $650 (sans trade-in)  ⟷  `gsmarena` Amazon US Black Friday deal: the Galaxy S26 Ultra and Z Fold8 Ultra are both $350 off
- 0.85 `androidcentral` Galaxy S26 FE has never looked better—a sweet 25% deal slides in before Black Friday  ⟷  `phonearena` Save a total of $600 with Samsung's top Galaxy S26 Ultra Black Friday deal while you can!
- 0.85 `androidauthority-news` Best Black Friday deals: Big discounts on phones, smartwatches, and more  ⟷  `9to5google` Best Black Friday deals now live: Google Pixel, Samsung, Amazon Echo, TVs, Anker, much more
- 0.85 `verge-google` Google is putting AI chats right on the homepage  ⟷  `9to5google` Google homepage rolling out AI-focused redesign that includes your Gemini chats [Video]
- 0.85 `gsmarena` Amazon US Black Friday deals: here are the best smartphone offers  ⟷  `9to5google` Best Black Friday deals now live: Google Pixel, Samsung, Amazon Echo, TVs, Anker, much more
- 0.85 `gsmarena` Black Friday deals from Amazon Germany: deals ranging from flagship to mid-range  ⟷  `gsmarena` Amazon UK's top Black Friday deals: camera flagships, foldables, mid-rangers and more
- 0.84 `gsmarena` Amazon US Black Friday deals: here are the best smartphone offers  ⟷  `androidauthority-news` Best Black Friday deals: Big discounts on phones, smartwatches, and more
- 0.84 `androidauthority-news` Best Black Friday deals: Big discounts on phones, smartwatches, and more  ⟷  `androidheadlines` Best Black Friday Deals 2026 on Android Phones, Tablets and TVs
- 0.84 `gsmarena` Amazon US Black Friday deals: here are the best smartphone offers  ⟷  `androidheadlines` Best Black Friday Deals 2026 on Android Phones, Tablets and TVs
- 0.83 `9to5google` Galaxy Z Fold 8 is $1,499 for Black Friday; its new lowest price ever, just not for everyone  ⟷  `gsmarena` Amazon US Black Friday deal: the Galaxy S26 Ultra and Z Fold8 Ultra are both $350 off

Pairs only the layered matcher merged (first 25):

- emb 0.89 / layered 0.34 (ent=0.50 tok=0.21) `androidauthority-news` Android’s controversial sideloading rules go global in January  ⟷  `androidcentral` Android's sideloading freedom is about to get a lot more complicated worldwide
- emb 0.85 / layered 0.46 (ent=0.60 tok=0.35 resid=0.16) `phonearena` Save a total of $600 with Samsung's top Galaxy S26 Ultra Black Friday deal while you can!  ⟷  `gsmarena` Amazon US Black Friday deal: the Galaxy S26 Ultra and Z Fold8 Ultra are both $350 off
- emb 0.83 / layered 0.50 (ent=0.57 tok=0.23 resid=0.08 +event(price)) `droidlife` Pixel 11 Pro Gets Biggest Price Cuts to Date  ⟷  `androidcentral` Lowest we've seen it—Pixel 11 Pro XL gets a huge 31% Black Friday price knock that's too hard to ignore
- emb 0.83 / layered 1.00 (shared primary link (tok=0.30)) `verge-android` Google is forcing Android app developers to properly support foldables  ⟷  `androidcentral` Your foldable phone deserves better, and Google is making developers deliver
- emb 0.83 / layered 0.47 (ent=0.67 tok=0.32 resid=0.13) `androidauthority-news` Galaxy Buds Active leak shows workout earbuds with ANC, ear hooks, IP68, and one odd omission  ⟷  `phonearena` Samsung's Galaxy Buds Active could be great gym earbuds, with one catch
- emb 0.82 / layered 0.44 (ent=0.43 tok=0.45 resid=0.30) `9to5google` Deals: Pixel Watch 5 hits Black Friday price at $100 off, Galaxy Watch 9 $110 off, Galaxy Tabs $300 off, more  ⟷  `androidcentral` The Pixel Watch 5 is finally below $300 thanks to this early Black Friday deal
- emb 0.82 / layered 0.42 (ent=0.00 tok=0.66 (headlines alone match)) `androidheadlines` Best Black Friday Deals 2026 on Android Phones, Tablets and TVs  ⟷  `gsmarena` Amazon Black Friday Week: best tablet deals
- emb 0.81 / layered 1.00 (shared primary link (tok=0.52)) `android-developers` Expanding Android developer verification in 2027  ⟷  `arstechnica-gadgets` Google will launch Android app verification requirement globally in January 2027
- emb 0.80 / layered 1.00 (shared primary link (tok=0.24)) `9to5google` Google Play wants Android apps to nail foldable basics by April 2027  ⟷  `verge-android` Google is forcing Android app developers to properly support foldables
- emb 0.80 / layered 0.32 (ent=0.40 tok=0.26 resid=0.08 guard(same-product,different-story)) `9to5google` Motorola Razr Flex leaks in real life with Fold 8 and iPhone Duo shape, mystery chipset  ⟷  `androidauthority-news` New Motorola Razr Flex renders offer best look yet at wide-body foldable
- emb 0.77 / layered 0.58 (ent=1.00 tok=0.24 resid=0.14) `androidauthority-news` Samsung is building a secure way for Galaxy users to erase their phones in One UI 9.5  ⟷  `androidauthority-news` One UI 9.5 could give lost phones a better chance of finding their way home with lock screen IMEI
- emb 0.77 / layered 1.00 (shared primary link (tok=0.28)) `verge-android` Google is forcing Android app developers to properly support foldables  ⟷  `androidauthority-news` Google’s mandatory foldable app guidelines are here, and optimized apps are coming in 2027
- emb 0.77 / layered 0.35 (ent=0.50 tok=0.23 resid=0.08 guard(same-product,different-story)) `androidpolice-news` Motorola's iPhone Duo rival is taking shape, and it could pack a surprise chipset  ⟷  `9to5google` Motorola’s iPhone Duo competitor, Razr Flex, leaks in detailed images [Gallery]
- emb 0.76 / layered 0.46 (ent=0.50 tok=0.43 resid=0.34) `androidpolice-news` Motorola's iPhone Duo rival is taking shape, and it could pack a surprise chipset  ⟷  `9to5google` Motorola Razr Flex leaks in real life with Fold 8 and iPhone Duo shape, mystery chipset
- emb 0.76 / layered 0.47 (ent=0.40 tok=0.30 resid=0.10 +event(leak)) `9to5google` Motorola’s iPhone Duo competitor, Razr Flex, leaks in detailed images [Gallery]  ⟷  `androidauthority-news` New Motorola Razr Flex renders offer best look yet at wide-body foldable
- emb 0.75 / layered 0.44 (ent=0.25 tok=0.59 (headlines alone match)) `arstechnica-gadgets` Google will launch Android app verification requirement globally in January 2027  ⟷  `androidauthority-news` Android’s controversial sideloading rules go global in January
- emb 0.74 / layered 1.00 (shared primary link (tok=0.13)) `9to5google` Google Play wants Android apps to nail foldable basics by April 2027  ⟷  `androidcentral` Your foldable phone deserves better, and Google is making developers deliver
- emb 0.74 / layered 1.00 (shared primary link (tok=0.30)) `android-developers` Expanding Android developer verification in 2027  ⟷  `androidcentral` Android's sideloading freedom is about to get a lot more complicated worldwide
- emb 0.73 / layered 1.00 (shared primary link (tok=0.14)) `androidauthority-news` Google’s mandatory foldable app guidelines are here, and optimized apps are coming in 2027  ⟷  `androidcentral` Your foldable phone deserves better, and Google is making developers deliver
- emb 0.73 / layered 0.45 (ent=0.83 tok=0.35 -framing(deal vs news) resid=0.17) `androidcentral` The Pixel Watch 5 is finally below $300 thanks to this early Black Friday deal  ⟷  `phonearena` Your Pixel Watch 5 could last longer on runs, thanks to a Play services update
- emb 0.72 / layered 0.29 (ent=0.25 tok=0.32) `android-developers` Expanding Android developer verification in 2027  ⟷  `androidauthority-news` Android’s controversial sideloading rules go global in January
- emb 0.69 / layered 0.16 (ent=0.36 tok=0.22 -framing(deal vs news) resid=0.00 guard(same-product,different-story)) `9to5google` Deals: Pixel Watch 5 hits Black Friday price at $100 off, Galaxy Watch 9 $110 off, Galaxy Tabs $300 off, more  ⟷  `phonearena` Your Pixel Watch 5 could last longer on runs, thanks to a Play services update
- emb 0.66 / layered 0.50 (ent=0.67 tok=0.36 resid=0.27) `androidauthority-news` One UI 9.5 beta quietly kills Audio Brief and Moments in Now Brief  ⟷  `androidauthority-news` One UI 9.5 could make booking an Uber part of your Now Brief routine
- emb 0.66 / layered 1.00 (shared primary link (tok=0.21)) `arstechnica-gadgets` Google will launch Android app verification requirement globally in January 2027  ⟷  `androidcentral` Android's sideloading freedom is about to get a lot more complicated worldwide
- emb 0.65 / layered 0.04 (ent=0.00 tok=0.07 (tok below floor)) `androidpolice-news` Motorola's iPhone Duo rival is taking shape, and it could pack a surprise chipset  ⟷  `androidauthority-news` New Motorola Razr Flex renders offer best look yet at wide-body foldable


## Current live dry run (20 Nov, 03:07 PST / 12:07 CET)

`python3 poster.py --lemmy-ua MistakeNot-modtools/1.0` (no state file, so the rolling count was seeded from AndroidNews's own !android posts):

- Rolling 24 h count: **5**, because v1 posted 5 at 00:00 PT. 0 posts are due now: it is quiet hours (00–06 PT), and nothing big is fresh.
- The biggest current cluster is Android app verification going global, from Ars, Android Authority and Android Central (score 8, BIG). It is skipped as a duplicate because cm0002 posted the Ars link at 11:20 PST yesterday.
- "Gemini on Mac can now use your computer" (3 outlets) is correctly skipped as not Android-related.
- Queued for 06:00 PT (15:00 CET): "Motorola details its Android 17 rollout plans for 29 phones" (score 4), then "Samsung's Auto Blocker won't switch off during calls in One UI 9.5" (score 3, which topic fatigue may lower).

## Feed health (checked 20 Nov ~11:50 CET)

| feed | result |
|---|---|
| 9to5Google, Android Authority news, Android Police news, Verge (Google and Android), Ars gadgets, GSMArena, Android Central, Droid Life, XDA news, Engadget, PhoneArena, Android Headlines, Samsung Newsroom, Android Developers blog, Google Keyword Android | OK (HTTP 200, parses, fresh) |
| Google Keyword Pixel | OK but quiet (newest 10 Nov) |
| Google Keyword Wear OS | OK but stale (newest 16 Jun 2026). The new path returns the same content. Keep it: it costs nothing. |
| Android Security Bulletin / Pixel bulletin (page polls) | OK. One poll timed out once during the replay, which is harmless. |
| Samsung Newsroom article pages | Feed is fine, but article pages time out from the box. v2 uses the feed headline, so it never needs to open the page. |
| TechCrunch Google tag | OK, but few Android items. Left off. |
| Android Police main / XDA main | OK, but duplicate or PC-heavy. The `/feed/news/` variants are used instead. |
| Reuters / AP | No public RSS. Not included. |
