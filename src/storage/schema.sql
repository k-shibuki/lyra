-- Lyra Database Schema
-- SQLite with FTS5 for full-text search

-- ============================================================
-- Schema Migration Tracking
-- ============================================================

-- Track applied migrations for version control
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Bibliographic Metadata (Normalized)
-- ============================================================

-- Works: Normalized bibliographic metadata
-- This is the single source of truth for academic paper metadata.
-- All bibliographic fields are only populated when actually retrieved from source.
CREATE TABLE IF NOT EXISTS works (
    canonical_id TEXT PRIMARY KEY,  -- doi:xxx, meta:xxx, title:xxx, etc.
    title TEXT NOT NULL,
    year INTEGER,
    published_date TEXT,  -- ISO format date
    venue TEXT,  -- Journal/Conference name
    doi TEXT,  -- Normalized DOI (no URL prefix)
    citation_count INTEGER DEFAULT 0,
    reference_count INTEGER DEFAULT 0,
    is_open_access BOOLEAN DEFAULT 0,
    oa_url TEXT,
    pdf_url TEXT,
    source_api TEXT NOT NULL,  -- Best source: semantic_scholar, openalex, web
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_works_doi ON works(doi);
CREATE INDEX IF NOT EXISTS idx_works_year ON works(year);
CREATE INDEX IF NOT EXISTS idx_works_source_api ON works(source_api);

-- Work Authors: Authors with preserved order
-- Position 0 = first author (used for author_display)
CREATE TABLE IF NOT EXISTS work_authors (
    id TEXT PRIMARY KEY,
    canonical_id TEXT NOT NULL,
    position INTEGER NOT NULL,  -- 0 = first author
    name TEXT NOT NULL,
    affiliation TEXT,
    orcid TEXT,  -- ORCID iD (without URL prefix)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canonical_id) REFERENCES works(canonical_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_work_authors_canonical ON work_authors(canonical_id);
CREATE INDEX IF NOT EXISTS idx_work_authors_position ON work_authors(canonical_id, position);

-- Work Identifiers: Provider-specific identifiers for lookup
-- Maps provider paper IDs (s2:xxx, openalex:Wxxx) to canonical_id
CREATE TABLE IF NOT EXISTS work_identifiers (
    id TEXT PRIMARY KEY,
    canonical_id TEXT NOT NULL,
    provider TEXT NOT NULL,  -- semantic_scholar, openalex, web
    provider_paper_id TEXT NOT NULL,  -- s2:xxx, openalex:Wxxx, etc.
    doi TEXT,  -- DOI from this provider
    pmid TEXT,
    pmcid TEXT,
    arxiv_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, provider_paper_id),
    FOREIGN KEY (canonical_id) REFERENCES works(canonical_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_work_identifiers_canonical ON work_identifiers(canonical_id);
CREATE INDEX IF NOT EXISTS idx_work_identifiers_provider_paper ON work_identifiers(provider_paper_id);
CREATE INDEX IF NOT EXISTS idx_work_identifiers_doi ON work_identifiers(doi);

-- ============================================================
-- Core Tables
-- ============================================================

-- Tasks: Research task definitions
-- ADR-0017: hypothesis is the central claim the task aims to verify
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    hypothesis TEXT NOT NULL,  -- Central hypothesis to verify (ADR-0017)
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME,
    config_json TEXT,  -- Task-specific configuration override
    result_summary TEXT,
    error_message TEXT
);

-- Queries: Search queries executed
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    query_type TEXT NOT NULL,  -- initial, expansion, mirror, reverse
    language TEXT DEFAULT 'ja',
    parent_query_id TEXT,  -- For sub-queries
    depth INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    executed_at DATETIME,
    engines_used TEXT,  -- JSON array
    result_count INTEGER DEFAULT 0,
    harvest_rate REAL DEFAULT 0,  -- useful_fragments / result_count
    cause_id TEXT,  -- Causal trace
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (parent_query_id) REFERENCES queries(id)
);
CREATE INDEX IF NOT EXISTS idx_queries_task ON queries(task_id);
CREATE INDEX IF NOT EXISTS idx_queries_parent ON queries(parent_query_id);

-- SERP Items: Search result items
CREATE TABLE IF NOT EXISTS serp_items (
    id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL,
    engine TEXT NOT NULL,
    rank INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    published_date TEXT,
    source_tag TEXT,  -- academic, government, news, blog, etc.
    page_number INTEGER DEFAULT 1,  -- SERP page number (1-indexed) for audit/reproducibility
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    clicked BOOLEAN DEFAULT 0,
    fetch_status TEXT,  -- pending, success, failed, skipped
    cause_id TEXT,
    FOREIGN KEY (query_id) REFERENCES queries(id)
);
CREATE INDEX IF NOT EXISTS idx_serp_query ON serp_items(query_id);
CREATE INDEX IF NOT EXISTS idx_serp_url ON serp_items(url);

-- Pages: Fetched pages
-- canonical_id links to works table for academic pages (replaces paper_metadata JSON)
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    final_url TEXT,  -- After redirects
    domain TEXT NOT NULL,
    page_type TEXT,  -- article, knowledge, forum, list, login_wall, academic_paper, etc.
    fetch_method TEXT,  -- http_client, browser_headless, browser_headful, academic_api
    http_status INTEGER,
    content_type TEXT,
    content_hash TEXT,  -- SHA256 of content
    content_length INTEGER,
    title TEXT,
    -- Academic paper reference (normalized; replaces paper_metadata JSON)
    canonical_id TEXT,  -- FK to works.canonical_id (NULL for non-academic pages)
    language TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    warc_path TEXT,
    screenshot_path TEXT,
    html_path TEXT,
    extracted_text_path TEXT,
    etag TEXT,
    last_modified TEXT,
    headers_json TEXT,
    error_message TEXT,
    cause_id TEXT,
    FOREIGN KEY (canonical_id) REFERENCES works(canonical_id)
);
CREATE INDEX IF NOT EXISTS idx_pages_domain ON pages(domain);
CREATE INDEX IF NOT EXISTS idx_pages_url ON pages(url);
CREATE INDEX IF NOT EXISTS idx_pages_canonical ON pages(canonical_id);

-- Fragments: Extracted text fragments
CREATE TABLE IF NOT EXISTS fragments (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL,
    fragment_type TEXT NOT NULL,  -- paragraph, heading, list, table, quote, figure, code, abstract
    position INTEGER,  -- Order in page
    text_content TEXT NOT NULL,
    heading_context TEXT,  -- Parent heading (legacy, single string)
    heading_hierarchy TEXT,  -- JSON: [{"level":1,"text":"..."}, {"level":2,"text":"..."}]
    element_index INTEGER,  -- Index within the current heading section
    char_offset_start INTEGER,
    char_offset_end INTEGER,
    text_hash TEXT,  -- For deduplication
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Scores
    bm25_score REAL,
    embed_score REAL,
    -- Relevance
    is_relevant BOOLEAN,
    relevance_reason TEXT,
    cause_id TEXT,
    FOREIGN KEY (page_id) REFERENCES pages(id)
);
CREATE INDEX IF NOT EXISTS idx_fragments_page ON fragments(page_id);
CREATE INDEX IF NOT EXISTS idx_fragments_hash ON fragments(text_hash);
CREATE INDEX IF NOT EXISTS idx_fragments_heading ON fragments(heading_context);

-- Claims: Atomic claims extracted from fragments
-- NOTE: Provenance (which fragment a claim was extracted from) is tracked via
-- edges with relation='origin', not via a JSON column. See ADR-0005.
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_type TEXT,  -- fact, opinion, prediction, etc.
    granularity TEXT,  -- atomic, composite
    expected_polarity TEXT,  -- positive, negative, neutral
    llm_claim_confidence REAL,  -- LLM's self-reported extraction quality (NOT truth confidence)
    claim_adoption_status TEXT DEFAULT 'adopted', -- Renamed, default changed from 'pending' 
    claim_rejection_reason TEXT,  -- rejection reason (audit)
    claim_rejected_at TEXT,  -- rejection timestamp
    verification_notes TEXT,
    timeline_json TEXT,  -- First seen, updated, etc.
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    cause_id TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_claims_task ON claims(task_id);

-- Edges: Evidence graph edges
-- relation types:
--   origin: provenance (Fragment→Claim) - which fragment a claim was extracted from
--   supports/refutes/neutral: NLI evidence (Fragment→Claim) - cross-source verification
--   cites: citation (Page→Page) - academic citation relationships
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,  -- claim, fragment, page
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,  -- origin, supports, refutes, neutral, cites
    nli_label TEXT,  -- From NLI model (supports/refutes/neutral); NULL for origin/cites
    nli_edge_confidence REAL,  -- NLI model output (calibrated); used in Bayesian update
    -- Academic / citation metadata
    -- citation_source is for CITES edges only (traceability; not used for filtering):
    --   "semantic_scholar" | "openalex" | "extraction"
    citation_source TEXT,
    citation_context TEXT,
    -- Domain category for ranking adjustment (see DomainCategory enum in domain_policy.py)
    source_domain_category TEXT,  -- PRIMARY/GOVERNMENT/ACADEMIC/TRUSTED/LOW/UNVERIFIED/BLOCKED
    target_domain_category TEXT,
    -- Human correction metadata
    edge_human_corrected BOOLEAN DEFAULT 0,
    edge_correction_reason TEXT,
    edge_corrected_at TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    cause_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
-- Index for efficient querying of contradiction relationships by domain categories
CREATE INDEX IF NOT EXISTS idx_edges_domain_categories ON edges(relation, source_domain_category, target_domain_category);
-- Partial unique index: prevent duplicate NLI edges for same (fragment, claim) pair.
-- ADR-0005: Same fragment-claim pair is evaluated only once; DB enforces uniqueness.
-- Only applies to NLI evidence edges (supports/refutes/neutral), not origin/cites.
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_nli_unique
    ON edges(source_type, source_id, target_type, target_id)
    WHERE source_type = 'fragment'
      AND target_type = 'claim'
      AND relation IN ('supports', 'refutes', 'neutral');

-- ============================================================
-- Domain & Engine Management
-- ============================================================

-- Domains: Per-domain policy and learning state
CREATE TABLE IF NOT EXISTS domains (
    domain TEXT PRIMARY KEY,
    domain_category TEXT DEFAULT 'unverified',
    qps_limit REAL DEFAULT 0.2,
    concurrent_limit INTEGER DEFAULT 1,
    headful_ratio REAL DEFAULT 0.1,
    tor_allowed BOOLEAN DEFAULT 1,
    tor_success_rate REAL DEFAULT 0.5,
    cooldown_minutes INTEGER DEFAULT 60,
    -- Metrics (EMA)
    success_rate_1h REAL DEFAULT 1.0,
    success_rate_24h REAL DEFAULT 1.0,
    captcha_rate REAL DEFAULT 0.0,
    http_error_rate REAL DEFAULT 0.0,
    block_score REAL DEFAULT 0.0,
    -- State
    last_success_at DATETIME,
    last_failure_at DATETIME,
    last_captcha_at DATETIME,
    cooldown_until DATETIME,
    skip_until DATETIME,
    skip_reason TEXT,
    -- Counters
    total_requests INTEGER DEFAULT 0,
    total_success INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    total_captchas INTEGER DEFAULT 0,
    -- Wayback Machine fallback tracking
    wayback_success_count INTEGER DEFAULT 0,
    wayback_failure_count INTEGER DEFAULT 0,
    -- IPv6 settings
    ipv6_enabled BOOLEAN DEFAULT 1,
    ipv6_success_rate REAL DEFAULT 0.5,
    ipv4_success_rate REAL DEFAULT 0.5,
    ipv6_preference TEXT DEFAULT 'auto',  -- ipv6_first, ipv4_first, auto
    -- IPv6 counters
    ipv6_attempts INTEGER DEFAULT 0,
    ipv6_successes INTEGER DEFAULT 0,
    ipv4_attempts INTEGER DEFAULT 0,
    ipv4_successes INTEGER DEFAULT 0,
    switch_count INTEGER DEFAULT 0,
    switch_success_count INTEGER DEFAULT 0,
    -- IPv6 timestamps
    last_ipv6_success_at DATETIME,
    last_ipv6_failure_at DATETIME,
    last_ipv4_success_at DATETIME,
    last_ipv4_failure_at DATETIME,
    -- HTTP/3 (QUIC) settings (ADR-0006)
    http3_detected BOOLEAN DEFAULT 0,
    http3_first_seen_at DATETIME,
    http3_last_seen_at DATETIME,
    -- HTTP/3 request counters
    browser_requests INTEGER DEFAULT 0,
    browser_http3_requests INTEGER DEFAULT 0,
    browser_successes INTEGER DEFAULT 0,
    http_client_requests INTEGER DEFAULT 0,
    http_client_successes INTEGER DEFAULT 0,
    -- HTTP/3 behavioral difference tracking
    behavioral_difference_ema REAL DEFAULT 0.0,
    browser_ratio_boost REAL DEFAULT 0.0,
    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Engine Health: Per-engine health metrics
CREATE TABLE IF NOT EXISTS engine_health (
    engine TEXT PRIMARY KEY,
    status TEXT DEFAULT 'closed',  -- closed, half-open, open
    weight REAL DEFAULT 1.0,
    qps_limit REAL DEFAULT 0.25,
    -- Metrics (EMA)
    success_rate_1h REAL DEFAULT 1.0,
    success_rate_24h REAL DEFAULT 1.0,
    captcha_rate REAL DEFAULT 0.0,
    median_latency_ms REAL DEFAULT 1000,
    http_error_rate REAL DEFAULT 0.0,
    normalization_failure_rate REAL DEFAULT 0.0,
    -- Circuit breaker
    consecutive_failures INTEGER DEFAULT 0,
    last_failure_at DATETIME,
    cooldown_until DATETIME,
    -- Counters
    total_queries INTEGER DEFAULT 0,
    total_success INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    daily_usage INTEGER DEFAULT 0,
    daily_limit INTEGER,
    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Lastmile Usage: Daily usage tracking for lastmile engines
-- Per ADR-0010: Track usage to enforce daily limits
CREATE TABLE IF NOT EXISTS lastmile_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine TEXT NOT NULL,
    date TEXT NOT NULL,  -- YYYY-MM-DD
    usage_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(engine, date)
);
CREATE INDEX IF NOT EXISTS idx_lastmile_usage_engine_date ON lastmile_usage(engine, date);

-- ============================================================
-- Job Scheduler
-- ============================================================

-- Jobs: Scheduled jobs (ADR-0010: unified via JobScheduler)
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    kind TEXT NOT NULL,  -- target_queue, verify_nli, citation_graph, serp, fetch, extract, embed, llm, nli
    priority INTEGER DEFAULT 50,  -- Lower = higher priority
    slot TEXT NOT NULL,  -- gpu, browser_headful, network_client, cpu_nlp
    state TEXT DEFAULT 'pending',  -- pending, queued, running, completed, failed, cancelled, awaiting_auth
    budget_pages INTEGER,
    budget_time_ms INTEGER,
    input_json TEXT,
    output_json TEXT,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    queued_at DATETIME,
    started_at DATETIME,
    finished_at DATETIME,
    cause_id TEXT,  -- Parent job/query ID for causal trace
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_task ON jobs(task_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_slot ON jobs(slot);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority);

-- ============================================================
-- Caching
-- ============================================================

-- SERP Cache
CREATE TABLE IF NOT EXISTS cache_serp (
    cache_key TEXT PRIMARY KEY,  -- Hash of normalized query + engines + time_range
    query_normalized TEXT NOT NULL,
    engines_json TEXT NOT NULL,
    time_range TEXT,
    result_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_serp_expires ON cache_serp(expires_at);

-- Fetch Cache (304 support)
CREATE TABLE IF NOT EXISTS cache_fetch (
    url_normalized TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    content_path TEXT,  -- Path to cached content
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_validated_at DATETIME,
    expires_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_cache_fetch_expires ON cache_fetch(expires_at);

-- Embeddings (persistent, replaces cache_embed)
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,  -- 'fragment' | 'claim'
    target_id TEXT NOT NULL,
    model_id TEXT NOT NULL,     -- 'BAAI/bge-m3'
    embedding_blob BLOB NOT NULL,
    dimension INTEGER NOT NULL,  -- 768
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(target_type, target_id, model_id)
);
CREATE INDEX IF NOT EXISTS idx_embeddings_target ON embeddings(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(target_type);

-- ============================================================
-- Logging & Audit
-- ============================================================

-- Event Log: Structured events for replay/audit
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,  -- query, fetch, extract, evaluate, decision, error
    level TEXT DEFAULT 'INFO',  -- DEBUG, INFO, WARNING, ERROR
    task_id TEXT,
    job_id TEXT,
    cause_id TEXT,
    component TEXT,  -- search, crawler, extractor, filter, etc.
    message TEXT,
    details_json TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_event_log_task ON event_log(task_id);
CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_timestamp ON event_log(timestamp);

-- LLM Extraction Errors: Track parse/validation failures for audit/debug
CREATE TABLE IF NOT EXISTS llm_extraction_errors (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    template_name TEXT NOT NULL,
    error_type TEXT NOT NULL,  -- json_parse, schema_validation
    response_preview TEXT,
    context_json TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_errors_task ON llm_extraction_errors(task_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_errors_template ON llm_extraction_errors(template_name);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_errors_type ON llm_extraction_errors(error_type);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_errors_created_at ON llm_extraction_errors(created_at);

-- Manual Intervention Log
CREATE TABLE IF NOT EXISTS intervention_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    domain TEXT,
    intervention_type TEXT NOT NULL,  -- captcha, login, cookie_banner, cloudflare
    notification_sent_at DATETIME,
    user_action_at DATETIME,
    completed_at DATETIME,
    result TEXT,  -- success, timeout, skipped, failed
    duration_seconds INTEGER,
    notes TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_intervention_task ON intervention_log(task_id);

-- Intervention Queue: Authentication queue (semi-automated operation)
-- Per ADR-0007: Human-in-the-Loop Authentication
CREATE TABLE IF NOT EXISTS intervention_queue (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    auth_type TEXT NOT NULL,  -- cloudflare, captcha, turnstile, hcaptcha, login, cookie
    priority TEXT DEFAULT 'medium',  -- high, medium, low
    status TEXT DEFAULT 'pending',  -- pending, in_progress, completed, skipped, expired
    queued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME,
    expires_at DATETIME,  -- Queue item expiration time
    session_data TEXT,  -- Session data after successful auth (JSON)
    notes TEXT,
    search_job_id TEXT,  -- Related search job ID (auto-requeue after resolve_auth)
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (search_job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_intervention_queue_task ON intervention_queue(task_id);
CREATE INDEX IF NOT EXISTS idx_intervention_queue_status ON intervention_queue(status);
CREATE INDEX IF NOT EXISTS idx_intervention_queue_domain ON intervention_queue(domain);
CREATE INDEX IF NOT EXISTS idx_intervention_queue_job ON intervention_queue(search_job_id);

-- ============================================================
-- Full-Text Search (FTS5)
-- ============================================================

-- FTS for fragments
CREATE VIRTUAL TABLE IF NOT EXISTS fragments_fts USING fts5(
    text_content,
    heading_context,
    content='fragments',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS fragments_ai AFTER INSERT ON fragments BEGIN
    INSERT INTO fragments_fts(rowid, text_content, heading_context)
    VALUES (NEW.rowid, NEW.text_content, NEW.heading_context);
END;

CREATE TRIGGER IF NOT EXISTS fragments_ad AFTER DELETE ON fragments BEGIN
    INSERT INTO fragments_fts(fragments_fts, rowid, text_content, heading_context)
    VALUES ('delete', OLD.rowid, OLD.text_content, OLD.heading_context);
END;

CREATE TRIGGER IF NOT EXISTS fragments_au AFTER UPDATE ON fragments BEGIN
    INSERT INTO fragments_fts(fragments_fts, rowid, text_content, heading_context)
    VALUES ('delete', OLD.rowid, OLD.text_content, OLD.heading_context);
    INSERT INTO fragments_fts(rowid, text_content, heading_context)
    VALUES (NEW.rowid, NEW.text_content, NEW.heading_context);
END;

-- FTS for claims
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    claim_text,
    content='claims',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
    INSERT INTO claims_fts(rowid, claim_text) VALUES (NEW.rowid, NEW.claim_text);
END;

CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
    INSERT INTO claims_fts(claims_fts, rowid, claim_text)
    VALUES ('delete', OLD.rowid, OLD.claim_text);
END;

CREATE TRIGGER IF NOT EXISTS claims_au AFTER UPDATE ON claims BEGIN
    INSERT INTO claims_fts(claims_fts, rowid, claim_text)
    VALUES ('delete', OLD.rowid, OLD.claim_text);
    INSERT INTO claims_fts(rowid, claim_text) VALUES (NEW.rowid, NEW.claim_text);
END;

-- ============================================================
-- Views
-- ============================================================

-- Active engines view
CREATE VIEW IF NOT EXISTS v_active_engines AS
SELECT 
    engine,
    status,
    weight,
    qps_limit,
    success_rate_1h,
    captcha_rate,
    median_latency_ms,
    daily_usage,
    daily_limit
FROM engine_health
WHERE status != 'open'
  AND (cooldown_until IS NULL OR cooldown_until < CURRENT_TIMESTAMP)
  AND (daily_limit IS NULL OR daily_usage < daily_limit);

-- Domain cooldown view
CREATE VIEW IF NOT EXISTS v_domain_cooldowns AS
SELECT 
    domain,
    cooldown_until,
    skip_until,
    skip_reason,
    block_score,
    captcha_rate
FROM domains
WHERE cooldown_until > CURRENT_TIMESTAMP
   OR skip_until > CURRENT_TIMESTAMP;

-- Task progress view
-- ADR-0017: hypothesis is the central claim the task aims to verify
CREATE VIEW IF NOT EXISTS v_task_progress AS
SELECT 
    t.id as task_id,
    t.hypothesis,
    t.status,
    t.created_at,
    COUNT(DISTINCT q.id) as query_count,
    COUNT(DISTINCT p.id) as page_count,
    COUNT(DISTINCT f.id) as fragment_count,
    COUNT(DISTINCT c.id) as claim_count
FROM tasks t
LEFT JOIN queries q ON t.id = q.task_id
LEFT JOIN serp_items s ON q.id = s.query_id
LEFT JOIN pages p ON s.url = p.url
LEFT JOIN fragments f ON p.id = f.page_id
LEFT JOIN claims c ON t.id = c.task_id
GROUP BY t.id;

-- ============================================================
-- Metrics & Policy (Auto-adaptation)
-- ============================================================

-- Global metrics snapshots (periodic system-wide metrics)
CREATE TABLE IF NOT EXISTS metrics_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Search quality metrics
    harvest_rate REAL,
    novelty_score REAL,
    duplicate_rate REAL,
    domain_diversity REAL,
    -- Exposure/avoidance metrics
    tor_usage_rate REAL,
    headful_rate REAL,
    referer_match_rate REAL,
    cache_304_rate REAL,
    captcha_rate REAL,
    http_error_403_rate REAL,
    http_error_429_rate REAL,
    -- OSINT quality metrics
    primary_source_rate REAL,
    citation_loop_rate REAL,
    narrative_diversity REAL,
    contradiction_rate REAL,
    timeline_coverage REAL,
    aggregator_rate REAL,
    -- System performance
    llm_time_ratio REAL,
    gpu_utilization REAL,
    browser_utilization REAL,
    -- Full snapshot as JSON
    full_snapshot_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshot_timestamp ON metrics_snapshot(timestamp);

-- Task metrics (per-task aggregated metrics)
CREATE TABLE IF NOT EXISTS task_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Counters
    total_queries INTEGER DEFAULT 0,
    total_pages_fetched INTEGER DEFAULT 0,
    total_fragments INTEGER DEFAULT 0,
    useful_fragments INTEGER DEFAULT 0,
    total_requests INTEGER DEFAULT 0,
    tor_requests INTEGER DEFAULT 0,
    headful_requests INTEGER DEFAULT 0,
    cache_304_hits INTEGER DEFAULT 0,
    revisit_count INTEGER DEFAULT 0,
    referer_matched INTEGER DEFAULT 0,
    -- Error counters
    captcha_count INTEGER DEFAULT 0,
    error_403_count INTEGER DEFAULT 0,
    error_429_count INTEGER DEFAULT 0,
    -- Source quality
    primary_sources INTEGER DEFAULT 0,
    total_sources INTEGER DEFAULT 0,
    unique_domains INTEGER DEFAULT 0,
    -- OSINT quality
    citation_loops_detected INTEGER DEFAULT 0,
    total_citations INTEGER DEFAULT 0,
    contradictions_found INTEGER DEFAULT 0,
    total_claims INTEGER DEFAULT 0,
    claims_with_timeline INTEGER DEFAULT 0,
    aggregator_sources INTEGER DEFAULT 0,
    -- Time tracking
    llm_time_ms INTEGER DEFAULT 0,
    total_time_ms INTEGER DEFAULT 0,
    -- Computed metrics JSON
    computed_metrics_json TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_task_metrics_task ON task_metrics(task_id);

-- Policy update history
CREATE TABLE IF NOT EXISTS policy_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    target_type TEXT NOT NULL,  -- engine, domain
    target_id TEXT NOT NULL,
    parameter TEXT NOT NULL,
    old_value REAL,
    new_value REAL,
    reason TEXT,
    metrics_snapshot_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_policy_updates_timestamp ON policy_updates(timestamp);
CREATE INDEX IF NOT EXISTS idx_policy_updates_target ON policy_updates(target_type, target_id);

-- Decision log for replay (lightweight reference to event_log)
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    decision_type TEXT NOT NULL,
    cause_id TEXT,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    context_json TEXT,
    duration_ms INTEGER DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_task ON decisions(task_id);
CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);

-- Replay sessions
CREATE TABLE IF NOT EXISTS replay_sessions (
    id TEXT PRIMARY KEY,
    original_task_id TEXT NOT NULL,
    replay_task_id TEXT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status TEXT DEFAULT 'pending',
    decisions_replayed INTEGER DEFAULT 0,
    decisions_diverged INTEGER DEFAULT 0,
    divergence_points_json TEXT,
    metrics_comparison_json TEXT,
    FOREIGN KEY (original_task_id) REFERENCES tasks(id),
    FOREIGN KEY (replay_task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_replay_sessions_original ON replay_sessions(original_task_id);

-- ============================================================
-- Calibration Evaluation 
-- ============================================================

-- Calibration evaluations: Brier score, ECE, reliability diagram data
CREATE TABLE IF NOT EXISTS calibration_evaluations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,  -- Source model identifier (e.g., "llm_extract", "nli_judge")
    brier_score REAL NOT NULL,  -- Brier score before calibration
    brier_score_calibrated REAL,  -- Brier score after calibration (NULL if no calibration)
    improvement_ratio REAL,  -- (before - after) / before
    expected_calibration_error REAL,  -- ECE
    samples_evaluated INTEGER NOT NULL,
    bins_json TEXT NOT NULL,  -- JSON array of bin data for reliability diagram
    calibration_version INTEGER,  -- Version of calibration params used
    evaluated_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_calibration_evaluations_source ON calibration_evaluations(source);
CREATE INDEX IF NOT EXISTS idx_calibration_evaluations_evaluated_at ON calibration_evaluations(evaluated_at);

-- ============================================================
-- Feedback & Override Tables
-- ============================================================

-- LoRA adapter management (ADR-0011: LoRA fine-tuning)
-- Tracks trained adapters, their metrics, and which adapter is currently active
CREATE TABLE IF NOT EXISTS adapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_name TEXT NOT NULL,           -- "v1", "v1.1", "v2" etc.
    adapter_path TEXT NOT NULL,           -- Path to adapter weights (e.g., "adapters/lora-v1/")
    base_model TEXT NOT NULL,             -- Base model name (e.g., "cross-encoder/nli-deberta-v3-small")
    samples_used INTEGER NOT NULL,        -- Number of training samples used
    brier_before REAL,                    -- Brier score before training
    brier_after REAL,                     -- Brier score after training
    shadow_accuracy REAL,                 -- Shadow evaluation accuracy
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 0           -- Whether this adapter is currently loaded in ML Server
);
CREATE INDEX IF NOT EXISTS idx_adapters_active ON adapters(is_active);
CREATE INDEX IF NOT EXISTS idx_adapters_created ON adapters(created_at);

-- NLI correction samples for ground-truth collection (ADR-0011: LoRA fine-tuning, ADR-0012: feedback)
CREATE TABLE IF NOT EXISTS nli_corrections (
    id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL,
    task_id TEXT,
    premise TEXT NOT NULL,               -- NLI premise snapshot (for training reproducibility)
    nli_hypothesis TEXT NOT NULL,         -- NLI hypothesis snapshot (ADR-0017: renamed to avoid conflict with task.hypothesis)
    predicted_label TEXT NOT NULL,       -- Original NLI prediction: supports/refutes/neutral
    predicted_confidence REAL NOT NULL,  -- Original confidence (0.0-1.0)
    correct_label TEXT NOT NULL,         -- Human-provided ground-truth: supports/refutes/neutral
    reason TEXT,                         -- Correction reason (audit)
    corrected_at TEXT NOT NULL,
    trained_adapter_id INTEGER,          -- NULL = not yet used for training, else = adapters.id
    FOREIGN KEY (edge_id) REFERENCES edges(id),
    FOREIGN KEY (trained_adapter_id) REFERENCES adapters(id)
);
CREATE INDEX IF NOT EXISTS idx_nli_corrections_edge ON nli_corrections(edge_id);
CREATE INDEX IF NOT EXISTS idx_nli_corrections_task ON nli_corrections(task_id);
CREATE INDEX IF NOT EXISTS idx_nli_corrections_corrected_at ON nli_corrections(corrected_at);
CREATE INDEX IF NOT EXISTS idx_nli_corrections_trained ON nli_corrections(trained_adapter_id);

-- Domain override rules (source of truth for feedback domain_block/unblock)
CREATE TABLE IF NOT EXISTS domain_override_rules (
    id TEXT PRIMARY KEY,
    domain_pattern TEXT NOT NULL,                 -- "example.com" or "*.example.com"
    decision TEXT NOT NULL,                       -- "block" | "unblock"
    reason TEXT NOT NULL,                         -- Required (audit)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    created_by TEXT DEFAULT 'feedback'            -- Audit trail
);
CREATE INDEX IF NOT EXISTS idx_domain_override_rules_active
    ON domain_override_rules(is_active, decision, updated_at);
CREATE INDEX IF NOT EXISTS idx_domain_override_rules_pattern
    ON domain_override_rules(domain_pattern);

-- Append-only audit log for domain overrides
CREATE TABLE IF NOT EXISTS domain_override_events (
    id TEXT PRIMARY KEY,
    rule_id TEXT,
    action TEXT NOT NULL,                         -- "domain_block" | "domain_unblock" | "domain_clear_override"
    domain_pattern TEXT NOT NULL,
    decision TEXT NOT NULL,                       -- "block" | "unblock" | "clear"
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'feedback'
);
CREATE INDEX IF NOT EXISTS idx_domain_override_events_created_at
    ON domain_override_events(created_at);
CREATE INDEX IF NOT EXISTS idx_domain_override_events_rule
    ON domain_override_events(rule_id);

-- ============================================================
-- Resource Deduplication Index (Cross-Worker Coordination)
-- ============================================================

-- Tracks claimed resources to prevent duplicate processing across workers
-- Uses INSERT OR IGNORE + SELECT pattern for race-condition-safe claims
CREATE TABLE IF NOT EXISTS resource_index (
    id TEXT PRIMARY KEY,
    identifier_type TEXT NOT NULL,  -- 'doi', 'pmid', 'arxiv', 'url'
    identifier_value TEXT NOT NULL, -- Normalized identifier value
    page_id TEXT,                   -- Associated page (if fetched/created)
    task_id TEXT,                   -- First task that discovered this resource
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
    worker_id INTEGER,              -- Worker that claimed this resource
    claimed_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(identifier_type, identifier_value)
);
CREATE INDEX IF NOT EXISTS idx_resource_index_status ON resource_index(status);
CREATE INDEX IF NOT EXISTS idx_resource_index_page ON resource_index(page_id);
CREATE INDEX IF NOT EXISTS idx_resource_index_type_value ON resource_index(identifier_type, identifier_value);

-- Task Pages: Task-scoped page associations for Citation Chasing
-- Tracks which pages belong to a task (for v_reference_candidates view scope)
CREATE TABLE IF NOT EXISTS task_pages (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    reason TEXT NOT NULL,  -- 'serp', 'academic_api', 'citation_chase', 'manual'
    depth INTEGER DEFAULT 0,  -- 0 = direct (SERP/API/manual), 1+ = citation chase depth
    source_page_id TEXT,  -- Page that cited this one (for citation_chase)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, page_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (page_id) REFERENCES pages(id),
    FOREIGN KEY (source_page_id) REFERENCES pages(id)
);
CREATE INDEX IF NOT EXISTS idx_task_pages_task ON task_pages(task_id);
CREATE INDEX IF NOT EXISTS idx_task_pages_page ON task_pages(page_id);
CREATE INDEX IF NOT EXISTS idx_task_pages_reason ON task_pages(reason);

-- ============================================================
-- Metrics Views
-- ============================================================

-- Latest global metrics
CREATE VIEW IF NOT EXISTS v_latest_metrics AS
SELECT *
FROM metrics_snapshot
ORDER BY timestamp DESC
LIMIT 1;

-- Recent policy updates
CREATE VIEW IF NOT EXISTS v_recent_policy_updates AS
SELECT 
    timestamp,
    target_type,
    target_id,
    parameter,
    old_value,
    new_value,
    reason
FROM policy_updates
ORDER BY timestamp DESC
LIMIT 100;

-- Task metrics summary
-- ADR-0017: hypothesis is the central claim the task aims to verify
CREATE VIEW IF NOT EXISTS v_task_metrics_summary AS
SELECT 
    t.id as task_id,
    t.hypothesis,
    t.status,
    tm.total_queries,
    tm.total_pages_fetched,
    tm.useful_fragments,
    tm.total_claims,
    CASE WHEN tm.total_pages_fetched > 0 
         THEN CAST(tm.useful_fragments AS REAL) / tm.total_pages_fetched 
         ELSE 0 END as harvest_rate,
    CASE WHEN tm.total_sources > 0 
         THEN CAST(tm.primary_sources AS REAL) / tm.total_sources 
         ELSE 0 END as primary_source_rate,
    CASE WHEN tm.total_time_ms > 0 
         THEN CAST(tm.llm_time_ms AS REAL) / tm.total_time_ms 
         ELSE 0 END as llm_time_ratio
FROM tasks t
LEFT JOIN task_metrics tm ON t.id = tm.task_id;

-- ============================================================
-- Evidence Graph Exploration Views (ADR: Sd_EVIDENCE_GRAPH_EXPLORATION)
-- Uses normalized works table instead of paper_metadata JSON
-- ============================================================

-- 1) Claim evidence aggregation (task-scoped via claims.task_id)
-- Provides counts, NLI-weighted support/refute, and Bayesian posterior mean
-- for truth confidence. ADR-0005: The true "truth confidence" is Bayesian-derived,
-- not llm_claim_confidence (which is extraction quality).
-- NOTE: Only NLI evidence edges (supports/refutes/neutral) are counted here.
-- Provenance edges (origin) are excluded - use v_claim_origins for provenance.
CREATE VIEW IF NOT EXISTS v_claim_evidence_summary AS
SELECT
    c.task_id,
    c.id AS claim_id,
    c.claim_text,
    -- Raw counts (for display / controversy score)
    SUM(CASE WHEN e.relation = 'supports' THEN 1 ELSE 0 END) AS support_count,
    SUM(CASE WHEN e.relation = 'refutes' THEN 1 ELSE 0 END) AS refute_count,
    SUM(CASE WHEN e.relation = 'neutral' THEN 1 ELSE 0 END) AS neutral_count,
    COUNT(e.id) AS evidence_count,
    -- NLI confidence stats
    MAX(COALESCE(e.nli_edge_confidence, 0.0)) AS max_nli_edge_confidence,
    AVG(COALESCE(e.nli_edge_confidence, 0.0)) AS avg_nli_edge_confidence,
    -- Weighted support/refute (sum of nli_edge_confidence per relation)
    SUM(CASE WHEN e.relation = 'supports' THEN COALESCE(e.nli_edge_confidence, 0.0) ELSE 0.0 END) AS support_weight,
    SUM(CASE WHEN e.relation = 'refutes' THEN COALESCE(e.nli_edge_confidence, 0.0) ELSE 0.0 END) AS refute_weight,
    -- Bayesian posterior mean: (1 + support_weight) / ((1 + support_weight) + (1 + refute_weight))
    -- Prior: Beta(1, 1) = uniform. Posterior: Beta(1 + support_weight, 1 + refute_weight)
    -- See ADR-0005 for detailed derivation.
    ROUND(
        (1.0 + SUM(CASE WHEN e.relation = 'supports' THEN COALESCE(e.nli_edge_confidence, 0.0) ELSE 0.0 END)) /
        (
            (1.0 + SUM(CASE WHEN e.relation = 'supports' THEN COALESCE(e.nli_edge_confidence, 0.0) ELSE 0.0 END)) +
            (1.0 + SUM(CASE WHEN e.relation = 'refutes' THEN COALESCE(e.nli_edge_confidence, 0.0) ELSE 0.0 END))
        ),
        4
    ) AS bayesian_truth_confidence
FROM claims c
LEFT JOIN edges e
  ON e.target_type = 'claim'
 AND e.target_id = c.id
 AND e.source_type = 'fragment'
 AND e.relation IN ('supports', 'refutes', 'neutral')  -- Exclude origin edges
GROUP BY c.task_id, c.id;

-- 2) Contradicting claims (supports + refutes)
CREATE VIEW IF NOT EXISTS v_contradictions AS
SELECT
    s.task_id,
    s.claim_id,
    s.claim_text,
    s.support_count,
    s.refute_count,
    s.neutral_count,
    s.evidence_count,
    CASE
      WHEN s.evidence_count <= 0 THEN 0.0
      ELSE (MIN(s.support_count, s.refute_count) * 1.0) / s.evidence_count
    END AS controversy_score
FROM v_claim_evidence_summary s
WHERE s.support_count > 0
  AND s.refute_count > 0;

-- 3) Claims with no evidence edges
CREATE VIEW IF NOT EXISTS v_unsupported_claims AS
SELECT
    s.task_id,
    s.claim_id,
    s.claim_text,
    s.evidence_count
FROM v_claim_evidence_summary s
WHERE s.evidence_count = 0;

-- 3b) Claim origins (provenance: which fragment/page a claim was extracted from)
-- Use this view to trace where claims came from. Separate from NLI evidence.
-- Includes bibliographic metadata from works table.
CREATE VIEW IF NOT EXISTS v_claim_origins AS
SELECT
    c.task_id,
    c.id AS claim_id,
    c.claim_text,
    e.id AS origin_edge_id,
    f.id AS fragment_id,
    f.text_content AS fragment_text,
    f.heading_context,
    p.id AS page_id,
    p.url,
    p.domain,
    p.title AS page_title,
    -- Bibliographic metadata from works table
    w.year,
    w.venue,
    w.doi,
    w.source_api,
    -- Author display: first author + et al.
    CASE
        WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 0 THEN 'unknown'
        WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 1 
            THEN (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id LIMIT 1)
        ELSE (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id ORDER BY wa.position LIMIT 1) || ' et al.'
    END AS author_display,
    e.created_at AS origin_created_at
FROM claims c
JOIN edges e
  ON e.target_type = 'claim'
 AND e.target_id = c.id
 AND e.source_type = 'fragment'
 AND e.relation = 'origin'
JOIN fragments f
  ON e.source_id = f.id
JOIN pages p
  ON f.page_id = p.id
LEFT JOIN works w
  ON p.canonical_id = w.canonical_id;

-- 4) Evidence chain (fragment -> claim with page provenance)
-- NOTE: Only NLI evidence edges (supports/refutes/neutral) are included.
-- For provenance (origin), use v_claim_origins.
-- Includes bibliographic metadata from works table.
CREATE VIEW IF NOT EXISTS v_evidence_chain AS
SELECT
    c.task_id,
    e.id AS edge_id,
    e.relation,
    e.nli_edge_confidence,
    f.id AS fragment_id,
    f.heading_context,
    p.id AS page_id,
    p.url,
    p.domain,
    c.id AS claim_id,
    c.claim_text,
    -- Bibliographic metadata from works table
    w.year,
    w.venue,
    w.doi,
    w.source_api,
    -- Author display: first author + et al.
    CASE
        WHEN w.canonical_id IS NULL THEN NULL
        WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 0 THEN 'unknown'
        WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 1 
            THEN (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id LIMIT 1)
        ELSE (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id ORDER BY wa.position LIMIT 1) || ' et al.'
    END AS author_display
FROM edges e
JOIN claims c
  ON e.target_type = 'claim'
 AND e.target_id = c.id
JOIN fragments f
  ON e.source_type = 'fragment'
 AND e.source_id = f.id
JOIN pages p
  ON f.page_id = p.id
LEFT JOIN works w
  ON p.canonical_id = w.canonical_id
WHERE e.source_type = 'fragment'
  AND e.target_type = 'claim'
  AND e.relation IN ('supports', 'refutes', 'neutral');  -- Exclude origin

-- 5) Hub pages (pages that support many claims) + citation counts
-- DEPRECATED: Consider using v_source_impact instead, which includes both
-- knowledge generation (origin edges) and corroboration (supports edges).
CREATE VIEW IF NOT EXISTS v_hub_pages AS
WITH page_claims AS (
  SELECT
      c.task_id,
      p.id AS page_id,
      p.url,
      p.title,
      p.domain,
      COUNT(DISTINCT c.id) AS claims_supported
  FROM edges e
  JOIN claims c
    ON e.target_type = 'claim'
   AND e.target_id = c.id
  JOIN fragments f
    ON e.source_type = 'fragment'
   AND e.source_id = f.id
  JOIN pages p
    ON f.page_id = p.id
  WHERE e.relation = 'supports'
  GROUP BY c.task_id, p.id
),
page_out AS (
  SELECT e.source_id AS page_id, COUNT(*) AS citation_count
  FROM edges e
  WHERE e.relation = 'cites' AND e.source_type = 'page' AND e.target_type = 'page'
  GROUP BY e.source_id
),
page_in AS (
  SELECT e.target_id AS page_id, COUNT(*) AS cited_by_count
  FROM edges e
  WHERE e.relation = 'cites' AND e.source_type = 'page' AND e.target_type = 'page'
  GROUP BY e.target_id
)
SELECT
    pc.task_id,
    pc.page_id,
    pc.url,
    pc.title,
    pc.domain,
    pc.claims_supported,
    COALESCE(po.citation_count, 0) AS citation_count,
    COALESCE(pi.cited_by_count, 0) AS cited_by_count
FROM page_claims pc
LEFT JOIN page_out po ON po.page_id = pc.page_id
LEFT JOIN page_in pi ON pi.page_id = pc.page_id;

-- 6) Citation flow (page -> page)
CREATE VIEW IF NOT EXISTS v_citation_flow AS
SELECT
    e.source_id AS citing_page_id,
    e.target_id AS cited_page_id,
    e.citation_source,
    e.created_at
FROM edges e
WHERE e.relation = 'cites'
  AND e.source_type = 'page'
  AND e.target_type = 'page';

-- 7) Orphan sources (evidence pages with zero inbound citations)
-- NOTE: Only NLI evidence edges (supports/refutes/neutral) are considered. Origin excluded.
CREATE VIEW IF NOT EXISTS v_orphan_sources AS
WITH evidence_pages AS (
  SELECT DISTINCT
      c.task_id,
      p.id AS page_id,
      p.url,
      p.title,
      p.domain
  FROM edges e
  JOIN claims c
    ON e.target_type = 'claim'
   AND e.target_id = c.id
  JOIN fragments f
    ON e.source_type = 'fragment'
   AND e.source_id = f.id
  JOIN pages p
    ON f.page_id = p.id
  WHERE e.source_type = 'fragment'
    AND e.target_type = 'claim'
    AND e.relation IN ('supports', 'refutes', 'neutral')  -- Exclude origin
),
inbound AS (
  SELECT e.target_id AS page_id, COUNT(*) AS cited_by_count
  FROM edges e
  WHERE e.relation = 'cites' AND e.source_type = 'page' AND e.target_type = 'page'
  GROUP BY e.target_id
)
SELECT
    ep.task_id,
    ep.page_id,
    ep.url,
    ep.title,
    ep.domain,
    COALESCE(i.cited_by_count, 0) AS cited_by_count
FROM evidence_pages ep
LEFT JOIN inbound i ON i.page_id = ep.page_id
WHERE COALESCE(i.cited_by_count, 0) = 0;

-- Helper CTE: evidence rows with extracted publication year (nullable)
-- Uses normalized works table instead of paper_metadata JSON.
-- Only NLI evidence edges (supports/refutes/neutral) are included. Origin excluded.
CREATE VIEW IF NOT EXISTS v__evidence_with_year AS
SELECT
    c.task_id,
    c.id AS claim_id,
    c.claim_text,
    e.relation,
    f.id AS fragment_id,
    p.id AS page_id,
    p.domain,
    w.year
FROM edges e
JOIN claims c
  ON e.target_type = 'claim'
 AND e.target_id = c.id
JOIN fragments f
  ON e.source_type = 'fragment'
 AND e.source_id = f.id
JOIN pages p
  ON f.page_id = p.id
LEFT JOIN works w
  ON p.canonical_id = w.canonical_id
WHERE e.source_type = 'fragment'
  AND e.target_type = 'claim'
  AND e.relation IN ('supports', 'refutes', 'neutral');  -- Exclude origin

-- 9) Evidence timeline (by year)
CREATE VIEW IF NOT EXISTS v_evidence_timeline AS
SELECT
    task_id,
    year,
    COUNT(DISTINCT fragment_id) AS fragment_count,
    COUNT(DISTINCT claim_id) AS claim_count
FROM v__evidence_with_year
GROUP BY task_id, year;

-- 10) Claim temporal support (supports only)
-- DEPRECATED: Use v_emerging_consensus instead for trend analysis.
CREATE VIEW IF NOT EXISTS v_claim_temporal_support AS
SELECT
    task_id,
    claim_id,
    claim_text,
    MIN(year) AS earliest_year,
    MAX(year) AS latest_year,
    CASE
      WHEN MIN(year) IS NULL OR MAX(year) IS NULL THEN NULL
      ELSE (MAX(year) - MIN(year))
    END AS year_span
FROM v__evidence_with_year
WHERE relation = 'supports'
GROUP BY task_id, claim_id;

-- 11) Emerging consensus (more recent support than older support)
CREATE VIEW IF NOT EXISTS v_emerging_consensus AS
WITH y AS (
  SELECT
      task_id,
      claim_id,
      claim_text,
      CASE WHEN year IS NOT NULL AND year >= (CAST(strftime('%Y','now') AS INTEGER) - 2) THEN 1 ELSE 0 END AS is_recent,
      relation
  FROM v__evidence_with_year
  WHERE relation = 'supports'
)
SELECT
    task_id,
    claim_id,
    claim_text,
    SUM(CASE WHEN is_recent = 1 THEN 1 ELSE 0 END) AS recent_support_count,
    SUM(CASE WHEN is_recent = 0 THEN 1 ELSE 0 END) AS older_support_count,
    (SUM(CASE WHEN is_recent = 1 THEN 1 ELSE 0 END) - SUM(CASE WHEN is_recent = 0 THEN 1 ELSE 0 END)) AS support_trend
FROM y
GROUP BY task_id, claim_id;

-- 12) Outdated evidence (newest support year far in the past)
CREATE VIEW IF NOT EXISTS v_outdated_evidence AS
WITH support_years AS (
  SELECT task_id, claim_id, claim_text, MAX(year) AS newest_evidence_year
  FROM v__evidence_with_year
  WHERE relation = 'supports'
  GROUP BY task_id, claim_id
)
SELECT
    task_id,
    claim_id,
    claim_text,
    newest_evidence_year,
    CASE
      WHEN newest_evidence_year IS NULL THEN NULL
      ELSE (CAST(strftime('%Y','now') AS INTEGER) - newest_evidence_year)
    END AS years_since_update
FROM support_years;

-- 13) Source authority (simple composite score)
-- Uses normalized works table for year extraction.
CREATE VIEW IF NOT EXISTS v_source_authority AS
WITH base AS (
  SELECT
      h.task_id,
      h.page_id,
      h.url,
      h.title,
      h.domain,
      h.claims_supported,
      h.citation_count,
      h.cited_by_count,
      w.year
  FROM v_hub_pages h
  JOIN pages p ON p.id = h.page_id
  LEFT JOIN works w ON w.canonical_id = p.canonical_id
)
SELECT
    task_id,
    page_id,
    url,
    title,
    domain,
    year,
    claims_supported,
    citation_count,
    cited_by_count,
    (claims_supported * 1.0) + (cited_by_count * 0.5) + (citation_count * 0.2) AS authority_score
FROM base;

-- 13b) Source impact (knowledge generation + corroboration)
-- Unlike v_source_authority which only counts NLI "supports" edges,
-- this view measures both knowledge generation (origin edges) and corroboration.
-- This ensures meta-analyses and systematic reviews are properly valued.
CREATE VIEW IF NOT EXISTS v_source_impact AS
WITH generated AS (
  SELECT
      c.task_id,
      p.id AS page_id,
      p.url,
      p.title,
      p.domain,
      COUNT(DISTINCT c.id) AS claims_generated,
      AVG(c.llm_claim_confidence) AS avg_claim_confidence
  FROM edges e
  JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
  JOIN fragments f ON e.source_type = 'fragment' AND e.source_id = f.id
  JOIN pages p ON f.page_id = p.id
  WHERE e.relation = 'origin'
  GROUP BY c.task_id, p.id
),
supported AS (
  SELECT c.task_id, p.id AS page_id, COUNT(DISTINCT e.id) AS claims_supported
  FROM edges e
  JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
  JOIN fragments f ON e.source_type = 'fragment' AND e.source_id = f.id
  JOIN pages p ON f.page_id = p.id
  WHERE e.relation = 'supports'
  GROUP BY c.task_id, p.id
)
SELECT
    g.task_id,
    g.page_id,
    g.url,
    g.title,
    g.domain,
    g.claims_generated,
    ROUND(g.avg_claim_confidence, 4) AS avg_claim_confidence,
    COALESCE(s.claims_supported, 0) AS claims_supported,
    ROUND(
        g.claims_generated 
        + (COALESCE(g.avg_claim_confidence, 0.5) * g.claims_generated * 0.5) 
        + (COALESCE(s.claims_supported, 0) * 0.3),
        2
    ) AS impact_score
FROM generated g
LEFT JOIN supported s ON g.task_id = s.task_id AND g.page_id = s.page_id;

-- 14) Controversy by era (bucket by decade using newest evidence year)
-- DEPRECATED: Low usage. Use v_contradictions + v_evidence_timeline for similar analysis.
CREATE VIEW IF NOT EXISTS v_controversy_by_era AS
WITH c AS (
  SELECT
      v.task_id,
      v.claim_id,
      v.claim_text,
      v.controversy_score,
      MAX(y.year) AS newest_year
  FROM v_contradictions v
  LEFT JOIN v__evidence_with_year y
    ON y.task_id = v.task_id AND y.claim_id = v.claim_id
  GROUP BY v.task_id, v.claim_id
)
SELECT
    task_id,
    CASE
      WHEN newest_year IS NULL THEN NULL
      ELSE (newest_year / 10) * 10
    END AS decade,
    COUNT(*) AS controversial_claims,
    AVG(controversy_score) AS avg_controversy_score
FROM c
GROUP BY task_id, decade;

-- 15) Citation age gap (citing year - cited year)
-- Uses normalized works table for year extraction.
CREATE VIEW IF NOT EXISTS v_citation_age_gap AS
WITH years AS (
  SELECT
      e.source_id AS citing_page_id,
      e.target_id AS cited_page_id,
      w1.year AS citing_year,
      w2.year AS cited_year
  FROM edges e
  JOIN pages p1 ON p1.id = e.source_id
  JOIN pages p2 ON p2.id = e.target_id
  LEFT JOIN works w1 ON w1.canonical_id = p1.canonical_id
  LEFT JOIN works w2 ON w2.canonical_id = p2.canonical_id
  WHERE e.relation = 'cites' AND e.source_type = 'page' AND e.target_type = 'page'
)
SELECT
    citing_page_id,
    cited_page_id,
    citing_year,
    cited_year,
    CASE
      WHEN citing_year IS NULL OR cited_year IS NULL THEN NULL
      ELSE (citing_year - cited_year)
    END AS age_gap
FROM years;

-- 16) Evidence freshness (avg age and recent support/refutation flags)
CREATE VIEW IF NOT EXISTS v_evidence_freshness AS
WITH cur AS (
  SELECT CAST(strftime('%Y','now') AS INTEGER) AS current_year
),
e AS (
  SELECT
      task_id,
      claim_id,
      claim_text,
      relation,
      year
  FROM v__evidence_with_year
  WHERE year IS NOT NULL
)
SELECT
    e.task_id,
    e.claim_id,
    e.claim_text,
    AVG(cur.current_year - e.year) AS avg_evidence_age,
    MAX(CASE WHEN e.relation = 'supports' AND e.year >= (cur.current_year - 2) THEN 1 ELSE 0 END) AS has_recent_support,
    MAX(CASE WHEN e.relation = 'refutes' AND e.year >= (cur.current_year - 2) THEN 1 ELSE 0 END) AS has_recent_refutation
FROM e, cur
GROUP BY e.task_id, e.claim_id;
