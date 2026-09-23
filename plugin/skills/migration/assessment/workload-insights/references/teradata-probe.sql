-- Run these one at a time, top to bottom. Keep the first statement that
-- succeeds and reports a row; that table is your source for the export.
-- Error 3807 means the table does not exist on this system and 3523 means
-- you lack rights on it — in both cases move to the next statement.

LOCKING ROW FOR ACCESS
SELECT TOP 1 'PDCRINFO.DBQLogTbl_Hst' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM PDCRINFO.DBQLogTbl_Hst;

LOCKING ROW FOR ACCESS
SELECT TOP 1 'PDCRINFO.DBQLogTbl' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM PDCRINFO.DBQLogTbl;

LOCKING ROW FOR ACCESS
SELECT TOP 1 'DBC.DBQLogTblV' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM DBC.DBQLogTblV;

LOCKING ROW FOR ACCESS
SELECT TOP 1 'DBC.DBQLogTbl' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM DBC.DBQLogTbl;
