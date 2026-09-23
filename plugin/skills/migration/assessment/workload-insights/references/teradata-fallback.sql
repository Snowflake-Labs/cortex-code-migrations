LOCKING ROW FOR ACCESS
SELECT
    CAST(QueryID AS BIGINT) AS QueryID,
    CAST(CollectTimeStamp AS DATE FORMAT 'YYYY-MM-DD') AS LogDate,
    CAST(CollectTimeStamp AS VARCHAR(30)) AS CollectTimeStamp,
    CAST(ProcID AS BIGINT) AS ProcID,
    CAST(SessionID AS INTEGER) AS SessionID,
    COALESCE(CAST(AppID AS VARCHAR(128)), '') AS AppID,
    CAST(StartTime AS VARCHAR(30)) AS StartTime,
    CAST(FirstStepTime AS VARCHAR(30)) AS FirstStepTime,
    CAST(FirstRespTime AS VARCHAR(30)) AS FirstRespTime,
    COALESCE(CAST(StatementType AS VARCHAR(30)), '') AS StatementType,
    COALESCE(DefaultDatabase, '') AS DefaultDatabase,
    COALESCE(StatementGroup, '') AS StatementGroup,
    CAST(ErrorCode AS INTEGER) AS ErrorCode,
    COALESCE(CAST(NumResultRows AS BIGINT), 0) AS NumResultRows,
    COALESCE(CAST(TotalIOCount AS BIGINT), 0) AS TotalIOCount,
    COALESCE(CAST(AMPCPUTime AS FLOAT), 0) AS AMPCPUTime,
    COALESCE(UserName, '') AS UserName
FROM DBC.DBQLogTbl
WHERE CollectTimeStamp BETWEEN TIMESTAMP 'YYYY-MM-DD HH:MM:SS'
                           AND TIMESTAMP 'YYYY-MM-DD HH:MM:SS';
