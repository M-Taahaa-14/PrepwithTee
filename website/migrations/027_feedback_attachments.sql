-- 027: screenshots ("snips") attached to feedback / issue reports.
-- JSON list of file names under data/feedback-snips/ on the server, served to admins
-- only by GET /api/admin/feedback/snips/{name}. save_feedback() falls back to putting
-- the names in the message while this column is missing.
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS attachments text;
