-- website/migrations/015_grade_thresholds_and_scores.sql
-- Ensure grade_thresholds and student_scores schemas are fully aligned.

ALTER TABLE student_scores ADD COLUMN IF NOT EXISTS set_by TEXT DEFAULT 'student';

CREATE INDEX IF NOT EXISTS idx_student_scores_user_syl ON student_scores(user_id, syllabus);
