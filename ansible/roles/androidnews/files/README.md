# Android news bot (lemdro.id)

Dry-run-first poster for a disclosed `AndroidNews@lemdro.id` account. It posts original headlines and links only, no generated summaries, and the trial targets `!android` alone.

## Usage

```bash
# Default is dry-run. Prints what would be posted and why other items were skipped.
python3 poster.py --dry-run

# Optional: widen the window, or use a cached Lemmy JWT for read-only community scans.
python3 poster.py --dry-run --lookback-hours 168 --jwt-file /tmp/lj

# Real posting (does nothing unless --post is set and ANDROIDNEWS_PASSWORD is in the env).
ANDROIDNEWS_PASSWORD='...' python3 poster.py --post
```

`--post` logs in as `AndroidNews` and creates link posts. It will not run without the env var. Passwords and JWTs are never printed.

## Config

See `config.yaml`. Per-source `community` and `enabled` flags are the extension point for later communities. Official Keyword / security-bulletin sources skip the rumor and listicle title filters. News sites do not.

Dedupe is by normalized URL and by title fingerprint, against recent posts already in the target community and against `state.json` after a successful post.
