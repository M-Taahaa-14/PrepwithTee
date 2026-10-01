-- 024: feedback forms now require the sender's email (tutor, 2026-09-30), so
-- the tutor can reply when a reported problem is fixed. Signed-in students get
-- their account email pre-filled; /api/feedback validates it.
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS email TEXT;
