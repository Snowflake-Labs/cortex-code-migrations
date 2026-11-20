-- SQL Server Agent jobs, their steps and schedules. Read-only: it only selects from msdb.
-- Have a DBA review it and run it with read access to msdb. Export the result as CSV with
-- column headers.
--
-- The `command` column can hold connection strings and parameter values, some of them secret.
-- Review the file and blank any value that is before you share it. The assessment reads the
-- package or procedure a step runs; it never copies a command into its output.
--
-- Steps of every type are returned, not only SSIS: the `subsystem` column says which ones run
-- a package ('SSIS') and which run T-SQL or a command, and all of them show what is scheduled.

SELECT
    j.name                  AS job_name,
    j.enabled               AS job_enabled,
    s.step_id,
    s.step_name,
    s.subsystem,
    s.database_name,
    s.command,
    sch.name                AS schedule_name,
    sch.enabled             AS schedule_enabled,
    sch.freq_type,
    sch.freq_interval,
    sch.freq_subday_type,
    sch.freq_subday_interval,
    sch.active_start_time,
    sv.last_run_date,
    sv.last_run_time,
    sv.last_run_outcome
FROM msdb.dbo.sysjobs AS j
JOIN msdb.dbo.sysjobsteps AS s
    ON s.job_id = j.job_id
LEFT JOIN msdb.dbo.sysjobschedules AS js
    ON js.job_id = j.job_id
LEFT JOIN msdb.dbo.sysschedules AS sch
    ON sch.schedule_id = js.schedule_id
LEFT JOIN msdb.dbo.sysjobservers AS sv
    ON sv.job_id = j.job_id
   AND sv.server_id = 0
ORDER BY j.name, s.step_id;
