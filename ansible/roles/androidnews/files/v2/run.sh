#!/bin/bash
# AndroidNews v2 bot runner. Password is read from a mode-600 file and
# never written to logs or the process command line.
cd /opt/android-news-bot/v2 || exit 1

exec 9>/opt/android-news-bot/v2/.lock
if ! flock -n 9; then
  echo "--- $(date -Is) skipped: already running" >> /opt/android-news-bot/v2/poster.log
  exit 0
fi

export ANDROIDNEWS_PASSWORD="$(tr -d '\n' < /opt/android-news-bot/.password)"
{
  echo "--- run start $(date -Is)"
  python3 /opt/android-news-bot/v2/poster.py --post
  echo "--- run end $(date -Is) exit $?"
} >> /opt/android-news-bot/v2/poster.log 2>&1
