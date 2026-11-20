CREATE OR REPLACE FUNCTION r.site_aggregates_activity(i text)
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
DECLARE
    count_ integer;
BEGIN
    SELECT
        count(*) INTO count_
    FROM (
        SELECT
            c.creator_id
        FROM
            comment c
            INNER JOIN person pe ON c.creator_id = pe.id
        WHERE
            c.published > (now()::timestamp - i::interval)
            AND pe.local = TRUE
            AND pe.bot_account = FALSE
        UNION
        SELECT
            p.creator_id
        FROM
            post p
            INNER JOIN person pe ON p.creator_id = pe.id
        WHERE
            p.published > (now()::timestamp - i::interval)
            AND pe.local = TRUE
            AND pe.bot_account = FALSE
        UNION
        SELECT
            pl.person_id
        FROM
            post_like pl
            INNER JOIN person pe ON pl.person_id = pe.id
        WHERE
            pl.published > (now()::timestamp - i::interval)
            AND pe.local = TRUE
            AND pe.bot_account = FALSE
        UNION
        SELECT
            cl.person_id
        FROM
            comment_like cl
            INNER JOIN person pe ON cl.person_id = pe.id
        WHERE
            cl.published > (now()::timestamp - i::interval)
            AND pe.local = TRUE
            AND pe.bot_account = FALSE) a;
    RETURN count_;
END;
$function$

;
