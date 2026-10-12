-- 004_status_rename.sql
-- Rename property status values to clearer names:
--   'passive'   -> 'inactive'  (rejected / deactivated listings)
--   'approving' -> 'pending'   (newly uploaded, awaiting admin approval)
-- Idempotent: re-running is a no-op once values are migrated.

UPDATE properties SET status = 'inactive' WHERE LOWER(TRIM(status)) = 'passive';
UPDATE properties SET status = 'pending'  WHERE LOWER(TRIM(status)) = 'approving';
