CREATE OR REPLACE FUNCTION r.community_aggregates_activity(i text)
 RETURNS TABLE(count_ bigint, community_id_ integer)
 LANGUAGE plpgsql
AS $function$
BEGIN
    RETURN query
    SELECT
        count(*),
        community_id
    FROM (
        SELECT
            c.creator_id,
            p.community_id
        FROM
            comment c
            INNER JOIN post p ON c.post_id = p.id
            INNER JOIN person pe ON c.creator_id = pe.id
        WHERE
            c.published > ('now'::timestamp - i::interval)
            AND pe.bot_account = FALSE
        UNION
        SELECT
            p.creator_id,
            p.community_id
        FROM
            post p
            INNER JOIN person pe ON p.creator_id = pe.id
        WHERE
            p.published > ('now'::timestamp - i::interval)
            AND pe.bot_account = FALSE
        UNION
        SELECT
            pl.person_id,
            p.community_id
        FROM
            post_like pl
            INNER JOIN post p ON pl.post_id = p.id
            INNER JOIN person pe ON pl.person_id = pe.id
        WHERE
            pl.published > ('now'::timestamp - i::interval)
            AND pe.bot_account = FALSE
        UNION
        SELECT
            cl.person_id,
            p.community_id
        FROM
            comment_like cl
            INNER JOIN comment c ON cl.comment_id = c.id
            INNER JOIN post p ON c.post_id = p.id
            INNER JOIN person pe ON cl.person_id = pe.id
        WHERE
            cl.published > ('now'::timestamp - i::interval)
            AND pe.bot_account = FALSE) a
GROUP BY
    community_id;
END;
$function$

