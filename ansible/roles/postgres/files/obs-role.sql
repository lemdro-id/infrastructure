-- lemdro.id observability: read-only Postgres access for the obs stack (P1). Idempotent; run as postgres in DB lemmy:
--   psql -X -v ON_ERROR_STOP=1 -d lemmy -f obs-role.sql
-- No restart, no reload, no pg_hba change (unix user obs connects by peer auth on the existing `local all all peer` line).
--
-- obs         LOGIN, read-only by default, pg_monitor + a few column-scoped federation reads. Never superuser.
-- obs_definer NOLOGIN, not superuser. Owns schema obs_api; its SECURITY DEFINER functions return AGGREGATE COUNTS
--             ONLY. obs gets EXECUTE on them and no grant at all on the per-user tables (person, post_like, ...),
--             so the voter/commenter identities never leave the database.
-- No grant anywhere on local_user, password_reset_request, private_message, email_verification, secret, site,
-- sent_activity, received_activity, or any private_key/public_key column.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '2s';   -- GRANT takes a brief lock on each table; never queue behind Lemmy for long

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'obs') THEN
    CREATE ROLE obs LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'obs_definer') THEN
    CREATE ROLE obs_definer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;
-- Re-assert attributes on every run (also undoes any manual drift).
ALTER ROLE obs LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5;
ALTER ROLE obs_definer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT pg_monitor TO obs;
ALTER ROLE obs SET default_transaction_read_only = on;
ALTER ROLE obs SET statement_timeout = '5s';            -- the interactions job raises this per session (SET is USERSET)
ALTER ROLE obs SET lock_timeout = '1s';
ALTER ROLE obs SET log_min_duration_statement = -1;     -- don't put our own polling in the slow log
ALTER ROLE obs SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE obs SET application_name = 'obs';
ALTER ROLE obs SET TimeZone = 'UTC';                    -- every obs timestamp is UTC

GRANT CONNECT ON DATABASE lemmy TO obs;
GRANT USAGE ON SCHEMA public TO obs, obs_definer;

-- Federation health (PLAN §6.1): exactly these, column-scoped where the table has other data.
GRANT SELECT ON public.federation_queue_state TO obs;
GRANT SELECT ON SEQUENCE public.sent_activity_id_seq TO obs;
GRANT SELECT (id, domain, updated, software, version) ON public.instance TO obs;
GRANT SELECT (instance_id) ON public.federation_blocklist TO obs;

-- obs_definer: only the columns the aggregate functions below read.
GRANT SELECT (id, post_id, creator_id, published, removed) ON public.comment TO obs_definer;
GRANT SELECT (id, community_id, creator_id, published, removed) ON public.post TO obs_definer;
GRANT SELECT (post_id, person_id, published) ON public.post_like TO obs_definer;
GRANT SELECT (comment_id, post_id, person_id, published) ON public.comment_like TO obs_definer;
GRANT SELECT (id, local, instance_id, bot_account) ON public.person TO obs_definer;
GRANT SELECT (id, name, local, instance_id) ON public.community TO obs_definer;
GRANT SELECT (id, domain) ON public.instance TO obs_definer;
GRANT SELECT (community_id, person_id) ON public.community_follower TO obs_definer;

CREATE SCHEMA IF NOT EXISTS obs_api AUTHORIZATION obs_definer;
ALTER SCHEMA obs_api OWNER TO obs_definer;
REVOKE ALL ON SCHEMA obs_api FROM PUBLIC;
GRANT USAGE ON SCHEMA obs_api TO obs;

-- Per-instance subscription counts (PLAN §6.1 N6): which remote instances matter most to us.
CREATE OR REPLACE FUNCTION obs_api.fed_instance_subscriptions()
  RETURNS TABLE (instance_id int, local_subs_to_them bigint, their_subs_to_us bigint)
  LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = pg_catalog, pg_temp
AS $f$
  SELECT i, sum(a)::bigint, sum(b)::bigint FROM (
    SELECT c.instance_id AS i, count(*) AS a, 0 AS b
      FROM public.community_follower f JOIN public.community c ON c.id = f.community_id
      JOIN public.person p ON p.id = f.person_id
     WHERE p.local AND NOT c.local GROUP BY 1
    UNION ALL
    SELECT p.instance_id, 0, count(*)
      FROM public.community_follower f JOIN public.community c ON c.id = f.community_id
      JOIN public.person p ON p.id = f.person_id
     WHERE c.local AND NOT p.local GROUP BY 1) t
  GROUP BY i
$f$;

-- Interactions (P1 headline): distinct users who commented / voted (post_like + comment_like) / posted / any of the three,
-- per community, over [p_from, p_to) (UTC day or ISO week, chosen by the caller), split by the user's home
-- (person.local, person.instance_id). Returns COUNTS ONLY; no person id, name or per-user row ever leaves this function.
--
-- scope            community        community_local home_instance  meaning
-- community        name@domain      t/f             NULL           every local community with activity; remote communities
--                                                                  with >= 1 local-user interaction, plus the top p_top_remote
--                                                                  remote communities by distinct active users
-- community_home   name@domain      t               domain|_other  local communities only; top p_top_home home instances per
--                                                                  (community, kind), the rest summed into '_other'
-- site             NULL             t/f/NULL        NULL           distinct users across communities (NULL = all communities)
-- site_home        NULL             NULL            domain|_other  all communities; top p_top_site_home home instances
-- users_local + users_remote = distinct users; on *_home rows users_remote is 0 for the local instance and users_local is 0
-- otherwise. Sums over home instances are exact (each person has exactly one home instance).
-- Defaults (review fix): bot accounts (person.bot_account) are not counted, and nothing inside mod-REMOVED content
-- counts (a removed post: the post, its comments and all votes on it; a removed comment: the comment and votes on it).
-- User-DELETED content still counts (the interaction happened). Pass p_exclude_bots/p_exclude_removed = false to count
-- everything; the source rows are never modified, so any past window can be recomputed either way.
-- Time is the row's own `published` (comment/post: the AP object's time; votes: when we stored them). Late federation can
-- still add to a past day, so the caller re-computes D-1 and D-2.
-- earlier 5-argument version (never applied live; kept for idempotency on test clusters)
DROP FUNCTION IF EXISTS obs_api.interactions(timestamptz, timestamptz, int, int, int);
CREATE OR REPLACE FUNCTION obs_api.interactions(
    p_from timestamptz, p_to timestamptz,
    p_top_home int DEFAULT 25, p_top_site_home int DEFAULT 50, p_top_remote int DEFAULT 200,
    p_exclude_bots boolean DEFAULT true, p_exclude_removed boolean DEFAULT true)
  RETURNS TABLE (scope text, community text, community_local boolean, home_instance text, kind text,
                 users_local bigint, users_remote bigint)
  LANGUAGE plpgsql STABLE SECURITY DEFINER
  SET search_path = pg_catalog, pg_temp
  SET work_mem = '64MB'
AS $f$
BEGIN
  IF p_from IS NULL OR p_to IS NULL OR p_to <= p_from OR p_to - p_from > interval '8 days' THEN
    RAISE EXCEPTION 'obs_api.interactions: window must be > 0 and <= 8 days (got % .. %)', p_from, p_to;
  END IF;
  IF least(p_top_home, p_top_site_home, p_top_remote) < 1 OR greatest(p_top_home, p_top_site_home, p_top_remote) > 1000 THEN
    RAISE EXCEPTION 'obs_api.interactions: top-N limits must be 1..1000';
  END IF;
  RETURN QUERY
  WITH ev AS MATERIALIZED (
    SELECT p.community_id, c.creator_id AS person_id, 'comment'::text AS kind
      FROM public.comment c JOIN public.post p ON p.id = c.post_id
     WHERE c.published >= p_from AND c.published < p_to
       AND NOT (p_exclude_removed AND (c.removed OR p.removed))
    UNION ALL
    SELECT p.community_id, p.creator_id, 'post' FROM public.post p
     WHERE p.published >= p_from AND p.published < p_to
       AND NOT (p_exclude_removed AND p.removed)
    UNION ALL
    SELECT p.community_id, l.person_id, 'vote' FROM public.post_like l JOIN public.post p ON p.id = l.post_id
     WHERE l.published >= p_from AND l.published < p_to
       AND NOT (p_exclude_removed AND p.removed)
    UNION ALL
    SELECT p.community_id, l.person_id, 'vote' FROM public.comment_like l JOIN public.post p ON p.id = l.post_id
      JOIN public.comment cm ON cm.id = l.comment_id
     WHERE l.published >= p_from AND l.published < p_to
       AND NOT (p_exclude_removed AND (cm.removed OR p.removed))
  ), d AS MATERIALIZED (
    SELECT DISTINCT e.community_id, e.person_id, e.kind FROM ev e
    UNION ALL
    SELECT DISTINCT e.community_id, e.person_id, 'any'::text FROM ev e
  ), dp AS MATERIALIZED (
    SELECT d.community_id, d.person_id, d.kind, pe.local AS user_local, pe.instance_id AS home_id, co.local AS comm_local
      FROM d JOIN public.person pe ON pe.id = d.person_id JOIN public.community co ON co.id = d.community_id
     WHERE NOT (p_exclude_bots AND pe.bot_account)
  ), comm AS MATERIALIZED (
    SELECT dp.community_id, dp.comm_local, dp.kind,
           count(*) FILTER (WHERE dp.user_local) AS ul, count(*) FILTER (WHERE NOT dp.user_local) AS ur
      FROM dp GROUP BY 1, 2, 3
  ), keep AS (
    SELECT k.community_id FROM comm k WHERE k.kind = 'any' AND (k.comm_local OR k.ul > 0)
    UNION
    SELECT t.community_id FROM (
      SELECT k.community_id FROM comm k WHERE k.kind = 'any' AND NOT k.comm_local
       ORDER BY k.ul + k.ur DESC, k.community_id LIMIT p_top_remote) t
  ), cname AS (
    SELECT co.id, co.name || '@' || i.domain AS label
      FROM public.community co JOIN public.instance i ON i.id = co.instance_id
     WHERE co.id IN (SELECT keep.community_id FROM keep)
  ), home AS (
    SELECT dp.community_id, dp.kind, dp.home_id, bool_or(dp.user_local) AS is_local, count(*) AS n
      FROM dp WHERE dp.comm_local GROUP BY 1, 2, 3
  ), home_r AS (
    SELECT h.*, row_number() OVER (PARTITION BY h.community_id, h.kind ORDER BY h.n DESC, h.home_id) AS rn FROM home h
  ), site AS (
    SELECT dp.comm_local, dp.kind,
           count(DISTINCT dp.person_id) FILTER (WHERE dp.user_local) AS ul,
           count(DISTINCT dp.person_id) FILTER (WHERE NOT dp.user_local) AS ur
      FROM dp GROUP BY GROUPING SETS ((dp.comm_local, dp.kind), (dp.kind))
  ), shome AS (
    SELECT dp.kind, dp.home_id, bool_or(dp.user_local) AS is_local, count(DISTINCT dp.person_id) AS n
      FROM dp GROUP BY 1, 2
  ), shome_r AS (
    SELECT s.*, row_number() OVER (PARTITION BY s.kind ORDER BY s.n DESC, s.home_id) AS rn FROM shome s
  )
  SELECT 'community', cn.label, k.comm_local, NULL::text, k.kind, k.ul, k.ur
    FROM comm k JOIN cname cn ON cn.id = k.community_id
  UNION ALL
  SELECT 'community_home', cn.label, true, CASE WHEN h.rn <= p_top_home THEN i.domain ELSE '_other' END, h.kind,
         sum(CASE WHEN h.is_local THEN h.n ELSE 0 END)::bigint, sum(CASE WHEN h.is_local THEN 0 ELSE h.n END)::bigint
    FROM home_r h JOIN cname cn ON cn.id = h.community_id JOIN public.instance i ON i.id = h.home_id
   GROUP BY 2, 4, 5
  UNION ALL
  SELECT 'site', NULL, s.comm_local, NULL, s.kind, s.ul, s.ur FROM site s
  UNION ALL
  SELECT 'site_home', NULL, NULL, CASE WHEN s.rn <= p_top_site_home THEN i.domain ELSE '_other' END, s.kind,
         sum(CASE WHEN s.is_local THEN s.n ELSE 0 END)::bigint, sum(CASE WHEN s.is_local THEN 0 ELSE s.n END)::bigint
    FROM shome_r s JOIN public.instance i ON i.id = s.home_id
   GROUP BY 4, 5;
END
$f$;

ALTER FUNCTION obs_api.fed_instance_subscriptions() OWNER TO obs_definer;
ALTER FUNCTION obs_api.interactions(timestamptz, timestamptz, int, int, int, boolean, boolean) OWNER TO obs_definer;
REVOKE ALL ON FUNCTION obs_api.fed_instance_subscriptions() FROM PUBLIC;
REVOKE ALL ON FUNCTION obs_api.interactions(timestamptz, timestamptz, int, int, int, boolean, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION obs_api.fed_instance_subscriptions() TO obs;
GRANT EXECUTE ON FUNCTION obs_api.interactions(timestamptz, timestamptz, int, int, int, boolean, boolean) TO obs;

-- Safety asserts (the run fails and rolls back if any is false).
DO $$ BEGIN
  IF (SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication FROM pg_roles WHERE rolname = 'obs')
     OR (SELECT rolsuper OR rolcanlogin OR rolcreaterole OR rolbypassrls FROM pg_roles WHERE rolname = 'obs_definer') THEN
    RAISE EXCEPTION 'obs/obs_definer gained a privileged attribute';
  END IF;
  IF has_table_privilege('obs', 'public.post_like', 'SELECT') OR has_table_privilege('obs', 'public.local_user', 'SELECT')
     OR has_column_privilege('obs', 'public.person', 'id', 'SELECT')
     OR has_column_privilege('obs_definer', 'public.person', 'private_key', 'SELECT')
     OR has_column_privilege('obs_definer', 'public.community', 'private_key', 'SELECT')
     OR has_schema_privilege('obs', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'obs grants are broader than intended';
  END IF;
END $$;
COMMIT;
