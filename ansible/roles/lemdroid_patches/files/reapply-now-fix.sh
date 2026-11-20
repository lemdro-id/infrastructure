#!/bin/bash
# lemdro.id local patch: keep Lemmy 0.19.21's r.community_aggregates_activity / r.site_aggregates_activity
# on now()::timestamp instead of plan-time-frozen 'now'::timestamp. Lemmy re-creates schema r on start.
# Runs as postgres from /etc/cron.d/lemdroid-now-fix. See /usr/local/lib/lemdroid/PATCHES.md.
#   reapply-now-fix.sh          -> apply mode: patched=noop, original=reapply, anything else=loud error, exit 2
#   reapply-now-fix.sh status   -> read-only: prints "<fn> patched|original|missing|unknown", exit 1 unless both patched
set -uo pipefail
L=/usr/local/lib/lemdroid/now-fix
MODE=${1:-apply}
FNS=(community_aggregates_activity site_aggregates_activity)
declare -A ORIG=([community_aggregates_activity]=93ae0ba6935c865ab791417ba06fdbd7 [site_aggregates_activity]=313d8fa49e71e75cc096708aa8f16ce6)
declare -A PATCHED=([community_aggregates_activity]=a60f33a66c248ded16263a07bb6a6016 [site_aggregates_activity]=fa67565ed015aafda650835f706a7387)
md5of() {
  timeout 20 psql -d lemmy -X -At -c "SELECT md5(prosrc) FROM pg_proc WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'r') AND proname = '$1'" 2>&1
}
state_of() {
  local m=$1 f=$2
  if [[ $m == "${PATCHED[$f]}" ]]; then echo patched
  elif [[ $m == "${ORIG[$f]}" ]]; then echo original
  elif [[ -z $m ]]; then echo missing
  else echo unknown; fi
}
rc=0; msgs=()
for f in "${FNS[@]}"; do
  m=$(md5of "$f"); st=$(state_of "$m" "$f")
  if [[ $MODE == status ]]; then
    echo "$f $st"; [[ $st == patched ]] || rc=1; continue
  fi
  case $st in
    patched) msgs+=("$f=ok") ;;
    original)
      out=$(timeout 60 psql -d lemmy -X -q -v ON_ERROR_STOP=1 -1 -f "$L/$f.patched.sql" 2>&1)
      st2=$(state_of "$(md5of "$f")" "$f")
      if [[ $st2 == patched ]]; then msgs+=("$f=REAPPLIED")
      else msgs+=("$f=REAPPLY-FAILED(${out//$'\n'/ })"); rc=1; fi ;;
    missing) msgs+=("$f=MISSING(schema r being recreated? retry next run)"); [[ $rc -lt 1 ]] && rc=1 ;;
    unknown) msgs+=("!!!ALERT!!! $f=UNKNOWN(md5 ${m//$'\n'/ }) body changed, Lemmy upgrade? NOT applying, see PATCHES.md"); rc=2 ;;
  esac
done
[[ $MODE == status ]] && exit $rc
echo "$(date -Is) ${msgs[*]}"
if [[ $rc -ne 0 ]]; then logger -p user.err -t lemdroid-now-fix "${msgs[*]}" 2>/dev/null || true; fi
exit $rc
