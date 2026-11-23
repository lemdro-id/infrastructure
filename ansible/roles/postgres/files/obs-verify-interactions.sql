-- Read-only cross-check of obs_api.interactions() against direct SQL counts for one window. Run as postgres:
--   psql -X -d lemmy -v from=2026-11-22 -v to=2026-11-23 -f obs-verify-interactions.sql
-- Prints counts only. Every "mismatches" line must be 0.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL statement_timeout = '180s';
SET LOCAL TimeZone = 'UTC';
WITH f AS (SELECT * FROM obs_api.interactions(:'from'::timestamptz, :'to'::timestamptz)),
ev AS (
  SELECT p.community_id, c.creator_id AS person_id, 'comment' AS kind FROM comment c JOIN post p ON p.id = c.post_id
   WHERE c.published >= :'from'::timestamptz AND c.published < :'to'::timestamptz
  UNION ALL SELECT p.community_id, p.creator_id, 'post' FROM post p
   WHERE p.published >= :'from'::timestamptz AND p.published < :'to'::timestamptz
  UNION ALL SELECT p.community_id, l.person_id, 'vote' FROM post_like l JOIN post p ON p.id = l.post_id
   WHERE l.published >= :'from'::timestamptz AND l.published < :'to'::timestamptz
  UNION ALL SELECT p.community_id, l.person_id, 'vote' FROM comment_like l JOIN post p ON p.id = l.post_id
   WHERE l.published >= :'from'::timestamptz AND l.published < :'to'::timestamptz),
ev2 AS (SELECT community_id, person_id, kind FROM ev UNION ALL SELECT community_id, person_id, 'any' FROM ev),
-- direct per-community counts, local communities only
direct_comm AS (
  SELECT co.name || '@' || i.domain AS label, e.kind,
         count(DISTINCT e.person_id) FILTER (WHERE pe.local) AS ul,
         count(DISTINCT e.person_id) FILTER (WHERE NOT pe.local) AS ur
    FROM ev2 e JOIN community co ON co.id = e.community_id AND co.local JOIN instance i ON i.id = co.instance_id
    JOIN person pe ON pe.id = e.person_id GROUP BY 1, 2),
direct_site AS (
  SELECT e.kind, count(DISTINCT e.person_id) FILTER (WHERE pe.local) AS ul,
         count(DISTINCT e.person_id) FILTER (WHERE NOT pe.local) AS ur
    FROM ev2 e JOIN person pe ON pe.id = e.person_id GROUP BY 1)
SELECT 'local communities (comm x kind) compared' AS check, count(*)::text AS value FROM direct_comm
UNION ALL
SELECT 'community mismatches', count(*)::text FROM direct_comm d
  FULL JOIN (SELECT * FROM f WHERE scope = 'community' AND community_local) x ON x.community = d.label AND x.kind = d.kind
 WHERE x.users_local IS DISTINCT FROM d.ul OR x.users_remote IS DISTINCT FROM d.ur
UNION ALL
SELECT 'site (all communities) mismatches', count(*)::text FROM direct_site d
  FULL JOIN (SELECT * FROM f WHERE scope = 'site' AND community_local IS NULL) x ON x.kind = d.kind
 WHERE x.users_local IS DISTINCT FROM d.ul OR x.users_remote IS DISTINCT FROM d.ur
UNION ALL
SELECT 'community_home sum != community mismatches', count(*)::text FROM (
  SELECT h.community, h.kind, sum(h.users_local + h.users_remote) AS s FROM f h WHERE h.scope = 'community_home' GROUP BY 1, 2) h
  FULL JOIN (SELECT * FROM f WHERE scope = 'community' AND community_local) c ON c.community = h.community AND c.kind = h.kind
 WHERE h.s IS DISTINCT FROM c.users_local + c.users_remote
UNION ALL
SELECT 'site_home sum != site mismatches', count(*)::text FROM (
  SELECT kind, sum(users_local + users_remote) AS s FROM f WHERE scope = 'site_home' GROUP BY 1) h
  FULL JOIN (SELECT * FROM f WHERE scope = 'site' AND community_local IS NULL) c ON c.kind = h.kind
 WHERE h.s IS DISTINCT FROM c.users_local + c.users_remote
UNION ALL
SELECT 'sample: site any users_local/users_remote', (SELECT users_local || '/' || users_remote FROM f WHERE scope = 'site' AND community_local IS NULL AND kind = 'any')
UNION ALL
SELECT 'rows returned by scope', (SELECT string_agg(scope || '=' || n, ' ') FROM (SELECT scope, count(*) n FROM f GROUP BY 1 ORDER BY 1) z);
ROLLBACK;
