-- 019: which Cambridge boards a student studies (multiple allowed).
-- Board slugs: 'o-level' | 'igcse' | 'a-level' (website/catalog.py BOARD_SHORT).
CREATE TABLE IF NOT EXISTS student_boards (
    user_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    board      TEXT NOT NULL CHECK (board IN ('o-level', 'igcse', 'a-level')),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, board)
);

-- Backfill from what students are already enrolled in, so nobody who is
-- mid-course gets the "which boards?" prompt for boards we can infer.
INSERT INTO student_boards (user_id, board)
SELECT DISTINCT e.user_id,
       CASE WHEN e.syllabus IN ('4024','5054','5070','2210','2058','2059') THEN 'o-level'
            WHEN e.syllabus IN ('0580','0625','0620','0478') THEN 'igcse'
            WHEN e.syllabus IN ('9709','9702','9618') THEN 'a-level' END
FROM enrollments e
WHERE e.status = 'active'
  AND e.syllabus IN ('4024','5054','5070','2210','2058','2059',
                     '0580','0625','0620','0478','9709','9702','9618')
ON CONFLICT DO NOTHING;
