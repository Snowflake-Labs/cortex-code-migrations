UNLOAD (
'SELECT
    query_id,
    username,
    database_name,
    query_type,
    status,
    start_time,
    end_time,
    elapsed_time,
    returned_rows
 FROM sys_query_history
 WHERE user_id > 1'
)
TO 's3://<bucket>/snowconvert/redshift_telemetry_'
IAM_ROLE '<role-arn>'
CSV
HEADER
PARALLEL OFF;
