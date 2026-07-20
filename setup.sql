-- SQL DDL for Blinkit Category-Discovery Intelligence Engine
-- Target Database: Supabase / Postgres (Free Tier)

-- Table 1: Raw Ingestion Layer
CREATE TABLE IF NOT EXISTS public.raw_feedback (
    review_id TEXT PRIMARY KEY, -- MD5 hash of source + platform_id
    source TEXT NOT NULL CHECK (source IN ('Google Play', 'App Store', 'Reddit')),
    timestamp TIMESTAMPTZ NOT NULL,
    text VARCHAR(800) NOT NULL, -- Cap at 800 characters to optimize token payloads
    app_version_approx TEXT, -- Version tag from Play Store where available
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table 2: Analytical Dimensions Layer (Altered to drop static check constraints for dynamic taxonomy)
CREATE TABLE IF NOT EXISTS public.ai_analytics (
    review_id TEXT PRIMARY KEY REFERENCES public.raw_feedback(review_id) ON DELETE CASCADE,
    theme TEXT NOT NULL, -- Dynamic category synthesized during Phase 4
    sentiment TEXT NOT NULL, -- Sentiment severity class
    user_type TEXT NOT NULL, -- User cohort segment
    root_cause VARCHAR(150) NOT NULL, -- Specific 5-7 word descriptive summary
    confidence_score INTEGER, -- 1 to 5 confidence score from the classifier
    audited BOOLEAN DEFAULT FALSE, -- Flagged if audited during Phase 6
    audit_theme TEXT, -- Auditor classification
    audit_sentiment TEXT, -- Auditor sentiment
    audit_user_type TEXT, -- Auditor cohort
    spot_checked BOOLEAN DEFAULT FALSE, -- Flagged if spot-checked by human
    spot_check_valid BOOLEAN, -- User feedback on classification validity
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

-- Table 4: Dynamic Search Keywords
CREATE TABLE IF NOT EXISTS public.filter_keywords (
    keyword TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table 5: Pipeline Audit Runs
CREATE TABLE IF NOT EXISTS public.pipeline_runs (
    id SERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    records_processed INTEGER NOT NULL DEFAULT 0,
    validation_results JSONB,
    metadata JSONB
);

-- Seed Initial Keywords for Blinkit / Zepto / Instamart Category Exploration
INSERT INTO public.filter_keywords (keyword) VALUES
('category'), ('explore'), ('recommend'), ('reorder'), ('never tried'),
('search'), ('browse'), ('out of stock'), ('substitute'), ('finding'),
('navigation'), ('layout'), ('fresh'), ('vegetables'), ('groceries'),
('fruits'), ('delivery'), ('slop'), ('clutter'), ('widget'), ('item')
ON CONFLICT (keyword) DO NOTHING;
