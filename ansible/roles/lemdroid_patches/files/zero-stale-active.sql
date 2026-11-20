-- lemdro.id explore fix (2026-11-20): zero stale community_aggregates.users_active_*
-- for LOCAL communities only.
-- Lemmy 0.19.21's scheduled job (r.community_aggregates_activity + UPDATE ... FROM temp table)
-- only writes communities that HAD activity in the window, so quiet ones keep their last
-- non-zero value forever. This writes 0 only where Lemmy's own definition gives no row:
-- no non-bot post, comment, post vote or comment vote in the community within the window
-- ('now'::timestamp - interval, same expression as Lemmy). It never writes a non-zero value,
-- so it cannot fight Lemmy's job. Idempotent; only touches rows that are currently non-zero.
-- Leaves no objects behind (DO block). Remove: rm /etc/cron.d/lemdroid-explore-active-zero
\set ON_ERROR_STOP on
SET statement_timeout = '300s';
SET lock_timeout = '10s';
DO $$
DECLARE
  r record;
  w record;
  active boolean;
  n_zeroed int := 0;
  t0 timestamptz := clock_timestamp();
  cols text[] := ARRAY['half_year','month','week','day'];
  ivs interval[] := ARRAY['6 months','1 month','1 week','1 day']::interval[];
  vals bigint[];
  i int;
  smallest_active int;
BEGIN
  FOR r IN
    SELECT co.id, co.name, a.users_active_half_year h, a.users_active_month m,
           a.users_active_week wk, a.users_active_day d
    FROM community co JOIN community_aggregates a ON a.community_id = co.id
    WHERE co.local
      AND (a.users_active_day <> 0 OR a.users_active_week <> 0
           OR a.users_active_month <> 0 OR a.users_active_half_year <> 0)
    ORDER BY co.id
  LOOP
    vals := ARRAY[r.h, r.m, r.wk, r.d];
    -- Walk windows from largest to smallest. Once a window is active, every larger one is
    -- active too (already known); once a window is quiet, every smaller one is quiet.
    smallest_active := 0;  -- 0 = none active yet
    FOR i IN 1..4 LOOP
      -- nothing left to zero in this window or any smaller one: stop checking
      EXIT WHEN vals[i] = 0 AND vals[i+1:4] = array_fill(0::bigint, ARRAY[4-i]);
      SELECT EXISTS (SELECT 1 FROM post p JOIN person pe ON pe.id = p.creator_id
                      WHERE p.community_id = r.id AND p.published > ('now'::timestamp - ivs[i])
                        AND NOT pe.bot_account)
          OR EXISTS (SELECT 1 FROM post p JOIN comment c ON c.post_id = p.id
                      JOIN person pe ON pe.id = c.creator_id
                      WHERE p.community_id = r.id AND c.published > ('now'::timestamp - ivs[i])
                        AND NOT pe.bot_account)
          OR EXISTS (SELECT 1 FROM post p JOIN post_like pl ON pl.post_id = p.id
                      JOIN person pe ON pe.id = pl.person_id
                      WHERE p.community_id = r.id AND pl.published > ('now'::timestamp - ivs[i])
                        AND NOT pe.bot_account)
          OR EXISTS (SELECT 1 FROM post p JOIN comment c ON c.post_id = p.id
                      JOIN comment_like cl ON cl.comment_id = c.id
                      JOIN person pe ON pe.id = cl.person_id
                      WHERE p.community_id = r.id AND cl.published > ('now'::timestamp - ivs[i])
                        AND NOT pe.bot_account)
        INTO active;
      EXIT WHEN NOT active;
      smallest_active := i;
    END LOOP;
    -- windows smallest_active+1 .. 4 are quiet
    FOR i IN (smallest_active + 1)..4 LOOP
      IF vals[i] <> 0 THEN
        EXECUTE format('UPDATE community_aggregates SET users_active_%s = 0 WHERE community_id = $1 AND users_active_%s <> 0', cols[i], cols[i]) USING r.id;
        RAISE NOTICE 'zeroed %.users_active_% (was %)', r.name, cols[i], vals[i];
        n_zeroed := n_zeroed + 1;
      END IF;
    END LOOP;
  END LOOP;
  RAISE NOTICE 'done: % values zeroed in % ms', n_zeroed,
    round(extract(epoch FROM clock_timestamp() - t0) * 1000);
END $$;
