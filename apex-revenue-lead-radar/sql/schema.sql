CREATE TABLE IF NOT EXISTS leads (
    id BIGSERIAL PRIMARY KEY,
    company_name TEXT NOT NULL,
    website TEXT,
    country TEXT,
    segment TEXT,
    trigger TEXT,
    evidence_url TEXT,
    evidence_summary TEXT,
    confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
    status TEXT NOT NULL DEFAULT 'needs_review',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deduplicate by company + evidence URL, including NULL evidence URLs.
CREATE UNIQUE INDEX IF NOT EXISTS leads_company_evidence_unique
ON leads (company_name, COALESCE(evidence_url, ''));

CREATE TABLE IF NOT EXISTS signal_events (
    id BIGSERIAL PRIMARY KEY,
    lead_id BIGINT REFERENCES leads(id) ON DELETE CASCADE,
    source_name TEXT,
    source_url TEXT,
    signal_type TEXT,
    signal_date DATE,
    raw_excerpt TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS leads_country_status_idx ON leads(country, status);
CREATE INDEX IF NOT EXISTS leads_created_at_idx ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS signal_events_lead_id_idx ON signal_events(lead_id);
