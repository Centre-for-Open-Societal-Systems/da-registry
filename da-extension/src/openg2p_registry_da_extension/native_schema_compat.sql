-- Add-only native outgestion compatibility for existing registry databases.
-- Topic IDs, source contracts and WebSub delivery checkpoints are preserved.
-- Platform 1.2.2-rc.557 added outgoing_topics.topic_type (NOT NULL) and
-- outgoing_topics.partner_id; a database created by an older release has
-- neither, and the outgestion beat task selects both on every tick.
DO $native_compat$
BEGIN
  IF to_regclass('public.outgoing_topics') IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='outgoing_topics' AND column_name='topic_type') THEN
      IF EXISTS (SELECT 1 FROM public.outgoing_topics WHERE register_id IS NULL) THEN
        RAISE EXCEPTION 'Legacy outgoing topics require an explicit register/partner migration';
      END IF;
      -- Existing topics were register topics; the platform model has no default.
      ALTER TABLE public.outgoing_topics ADD COLUMN IF NOT EXISTS topic_type varchar NOT NULL DEFAULT 'REGISTER';
      ALTER TABLE public.outgoing_topics ALTER COLUMN topic_type DROP DEFAULT;
    END IF;
    -- Optional owner of a partner-scoped topic; nullable in the platform model.
    ALTER TABLE public.outgoing_topics ADD COLUMN IF NOT EXISTS partner_id varchar;
  END IF;
END;
$native_compat$;
