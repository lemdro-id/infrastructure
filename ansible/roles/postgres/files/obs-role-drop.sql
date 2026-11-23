-- Undo obs-role.sql (run as postgres in DB lemmy). Removes only what obs-role.sql created; Lemmy's data is untouched.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '2s';
DROP SCHEMA IF EXISTS obs_api CASCADE;
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'obs') THEN
    EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM obs';
    EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM obs';
    EXECUTE 'REVOKE ALL ON SCHEMA public FROM obs';
    EXECUTE 'REVOKE ALL ON DATABASE lemmy FROM obs';
    EXECUTE 'REVOKE pg_monitor FROM obs';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'obs_definer') THEN
    EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM obs_definer';
    EXECUTE 'REVOKE ALL ON SCHEMA public FROM obs_definer';
  END IF;
END $$;
-- Column-level grants are not covered by REVOKE ... ON ALL TABLES; revoke them explicitly.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT DISTINCT table_name, grantee FROM information_schema.column_privileges
            WHERE table_schema = 'public' AND grantee IN ('obs', 'obs_definer') LOOP
    EXECUTE format('REVOKE ALL (%s) ON public.%I FROM %I',
      (SELECT string_agg(quote_ident(column_name), ', ') FROM information_schema.column_privileges
        WHERE table_schema = 'public' AND table_name = r.table_name AND grantee = r.grantee), r.table_name, r.grantee);
  END LOOP;
END $$;
DROP ROLE IF EXISTS obs_definer;
DROP ROLE IF EXISTS obs;   -- per-role settings (ALTER ROLE ... SET) go with it
COMMIT;
