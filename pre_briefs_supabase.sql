-- Signal Society V2 compatibility: persistent Living Pre-Briefs
-- Run this in Supabase SQL Editor if the deployed app uses Supabase.
CREATE TABLE IF NOT EXISTS public.pre_briefs (
    id text PRIMARY KEY,
    status text NOT NULL DEFAULT 'open',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    data jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pre_briefs_status_updated
    ON public.pre_briefs (status, updated_at DESC);
