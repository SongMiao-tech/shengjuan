CREATE TABLE IF NOT EXISTS public.user_audiobooks (
  id text PRIMARY KEY,
  uid text NOT NULL,
  title text NOT NULL,
  narrator text,
  dur_s numeric,
  size_bytes integer,
  audio_b64 text NOT NULL,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_audiobooks_uid ON public.user_audiobooks (uid, created_at DESC);
