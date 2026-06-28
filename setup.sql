-- SQL DDL for AI-Native Review Discovery Engine
-- Target Database: Supabase / Postgres (Free Tier)

-- Table 1: Raw Ingestion Layer
CREATE TABLE IF NOT EXISTS public.raw_feedback (
    review_id TEXT PRIMARY KEY, -- MD5 hash of source + platform_id
    source TEXT NOT NULL CHECK (source IN ('Google Play', 'App Store', 'Reddit')),
    timestamp TIMESTAMPTZ NOT NULL,
    text VARCHAR(800) NOT NULL, -- Cap at 800 characters to optimize token payloads
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table 2: Analytical Dimensions Layer
CREATE TABLE IF NOT EXISTS public.ai_analytics (
    review_id TEXT PRIMARY KEY REFERENCES public.raw_feedback(review_id) ON DELETE CASCADE,
    theme TEXT NOT NULL CHECK (theme IN ('Echo Chamber', 'Smart Shuffle Failure', 'Niche Genre Blending', 'UI/UX Clutter', 'Ad & Subscription Barriers', 'App Performance & Crashes', 'Offline Sync & Connection', 'Accurate Recommendations', 'Great UI/UX', 'Smart Curation', 'Positive')),
    sentiment TEXT NOT NULL CHECK (sentiment IN ('Negative', 'Highly Frustrated', 'Disappointed', 'Positive')),
    user_type TEXT NOT NULL CHECK (user_type IN ('Power User', 'Casual Listener', 'Audiophile', 'Playlist Curator')),
    root_cause VARCHAR(100) NOT NULL, -- Concise 5-7 word descriptive summary
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- View 3: Delta State Management View (Left Anti-Join)
CREATE OR REPLACE VIEW public.unprocessed_feedback AS
SELECT 
    r.review_id, 
    r.text
FROM 
    public.raw_feedback r
LEFT JOIN 
    public.ai_analytics a ON r.review_id = a.review_id
WHERE 
    a.review_id IS NULL;

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_raw_feedback_timestamp ON public.raw_feedback(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_raw_feedback_source ON public.raw_feedback(source);
CREATE INDEX IF NOT EXISTS idx_ai_analytics_theme ON public.ai_analytics(theme);
CREATE INDEX IF NOT EXISTS idx_ai_analytics_user_type ON public.ai_analytics(user_type);
