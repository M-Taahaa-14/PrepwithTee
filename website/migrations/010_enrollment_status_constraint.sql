-- migrations/010_enrollment_status_constraint.sql

-- 1. Migrate paused status to inactive
UPDATE enrollments SET status = 'inactive' WHERE status = 'paused';

-- 2. Drop the constraint if it exists and add/re-add it
ALTER TABLE enrollments DROP CONSTRAINT IF EXISTS enrollments_status_check;
ALTER TABLE enrollments ADD CONSTRAINT enrollments_status_check CHECK (status IN ('active', 'inactive'));
