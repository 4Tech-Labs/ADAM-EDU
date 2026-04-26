-- Issue #23 secondary RLS policies.
-- Backend SQLAlchemy remains the primary authorization boundary.
-- Any invite token hash comparison performed outside SQL must use
-- hmac.compare_digest() in the backend auth flows introduced after this issue.

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE allowed_email_domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE university_sso_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY profiles_self ON profiles
  FOR ALL
  USING (id = auth.uid()::text)
  WITH CHECK (id = auth.uid()::text);

CREATE POLICY memberships_self ON memberships
  FOR SELECT
  USING (user_id = auth.uid()::text);

CREATE POLICY courses_by_university ON courses
  FOR SELECT
  USING (
    university_id IN (
      SELECT m.university_id
      FROM memberships m
      WHERE m.user_id = auth.uid()::text
        AND m.status = 'active'
    )
  );

CREATE POLICY course_memberships_self ON course_memberships
  FOR SELECT
  USING (
    membership_id IN (
      SELECT m.id
      FROM memberships m
      WHERE m.user_id = auth.uid()::text
        AND m.status = 'active'
    )
  );

-- Backend-managed tables stay deny-all from client-side access.
CREATE POLICY deny_all ON invites
  FOR ALL
  USING (false)
  WITH CHECK (false);

CREATE POLICY deny_all ON allowed_email_domains
  FOR ALL
  USING (false)
  WITH CHECK (false);

CREATE POLICY deny_all ON university_sso_configs
  FOR ALL
  USING (false)
  WITH CHECK (false);

-- Issue #108: teacher authoring progress over Supabase Realtime.
-- This section enables safe client-side SELECT for owned authoring jobs only.
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE authoring_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE case_grades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS assignments_teacher_owner_select ON assignments;
CREATE POLICY assignments_teacher_owner_select ON assignments
  FOR SELECT
  USING (teacher_id = auth.uid()::text);

DROP POLICY IF EXISTS authoring_jobs_teacher_owner_select ON authoring_jobs;
CREATE POLICY authoring_jobs_teacher_owner_select ON authoring_jobs
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM assignments a
      WHERE a.id = authoring_jobs.assignment_id
        AND a.teacher_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS case_grades_teacher_select ON case_grades;
CREATE POLICY case_grades_teacher_select ON case_grades
  FOR SELECT
  TO authenticated
  USING (
    (select auth.uid()) IS NOT NULL
    AND course_id IN (
      SELECT c.id
      FROM courses c
      JOIN memberships m ON m.id = c.teacher_membership_id
      WHERE m.user_id = (select auth.uid())::text
        AND m.role = 'teacher'
        AND m.status = 'active'
    )
  );

DROP POLICY IF EXISTS case_grades_student_self_select ON case_grades;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
      AND schemaname = 'public'
      AND tablename = 'authoring_jobs'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.authoring_jobs;
  END IF;
END
$$;
