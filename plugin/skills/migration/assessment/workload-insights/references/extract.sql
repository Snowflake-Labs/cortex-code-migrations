EXEC sys.sp_query_store_flush_db;
GO

DECLARE @Days int = 30;  -- plugin fills this from the user's answer; 30 is the recommendation, not a lock

WITH s AS (
    SELECT
        p.query_id,
        SUM(rs.count_executions)                   AS executions,
        SUM(rs.avg_duration * rs.count_executions) AS duration_us,
        SUM(rs.avg_cpu_time * rs.count_executions) AS cpu_us,
        MAX(rs.max_duration)                       AS max_duration_us,
        MIN(rs.first_execution_time)               AS first_seen,
        MAX(rs.last_execution_time)                AS last_seen
    FROM sys.query_store_runtime_stats AS rs
    JOIN sys.query_store_plan AS p
        ON p.plan_id = rs.plan_id
    WHERE rs.execution_type = 0
      AND rs.last_execution_time >= DATEADD(DAY, -@Days, SYSDATETIMEOFFSET())
    GROUP BY p.query_id
)
SELECT
    DB_NAME()                       AS database_name,
    s.query_id,
    q.object_id,
    OBJECT_SCHEMA_NAME(q.object_id) AS object_schema,
    OBJECT_NAME(q.object_id)        AS object_name,
    s.executions,
    s.duration_us,
    s.cpu_us,
    s.max_duration_us,
    s.first_seen,
    s.last_seen,
    qt.query_sql_text
FROM s
JOIN sys.query_store_query AS q
    ON q.query_id = s.query_id
   AND q.is_internal_query = 0
JOIN sys.query_store_query_text AS qt
    ON qt.query_text_id = q.query_text_id;
