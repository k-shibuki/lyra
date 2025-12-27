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
-- Core Tables
-- ============================================================

-- Tasks: Research task definitions
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    final_url TEXT,  -- After redirects
    domain TEXT NOT NULL,
    page_type TEXT,  -- article, knowledge, forum, list, login_wall, etc.
    fetch_method TEXT,  -- http_client, browser_headless, browser_headful
    http_status INTEGER,
    content_type TEXT,
    content_hash TEXT,  -- SHA256 of content
    content_length INTEGER,
    title TEXT,
    -- Academic paper metadata (Abstract Only strategy; stored as JSON string)
    paper_metadata TEXT,
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
    cause_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_pages_domain ON pages(domain);
CREATE INDEX IF NOT EXISTS idx_pages_url ON pages(url);

-- Fragments: Extracted text fragments
CREATE TABLE IF NOT EXISTS fragments (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL,
    fragment_type TEXT NOT NULL,  -- paragraph, heading, list, table, quote, figure, code
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
    rerank_score REAL,
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
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_type TEXT,  -- fact, opinion, prediction, etc.
    granularity TEXT,  -- atomic, composite
    expected_polarity TEXT,  -- positive, negative, neutral
    claim_confidence REAL, -- Renamed from confidence_score 
    source_fragment_ids TEXT,  -- JSON array
    claim_adoption_status TEXT DEFAULT 'adopted', -- Renamed, default changed from 'pending' 
    claim_rejection_reason TEXT,  -- NEW: rejection reason (audit)
    claim_rejected_at TEXT,  -- NEW: rejection timestamp
    supporting_count INTEGER DEFAULT 0,
    refuting_count INTEGER DEFAULT 0,
    neutral_count INTEGER DEFAULT 0,
    verification_notes TEXT,
    timeline_json TEXT,  -- First seen, updated, etc.
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    cause_id TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_claims_task ON claims(task_id);

-- Edges: Evidence graph edges
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,  -- claim, fragment, page
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,  -- supports, refutes, cites, neutral
    confidence REAL,
    nli_label TEXT,  -- From NLI model
    nli_confidence REAL,
    -- Academic / citation metadata
    -- citation_source is for CITES edges only (traceability; not used for filtering):
    --   "semantic_scholar" | "openalex" | "extraction"
    citation_source TEXT,
    citation_context TEXT,
    -- Domain category for ranking adjustment (see DomainCategory enum in domain_policy.py)
    source_domain_category TEXT,  -- PRIMARY/GOVERNMENT/ACADEMIC/TRUSTED/LOW/UNVERIFIED/BLOCKED
    target_domain_category TEXT,
    -- Human correction metadata ( / )
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

-- Jobs: Scheduled jobs
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    kind TEXT NOT NULL,  -- serp, fetch, extract, embed, rerank, llm_fast, llm_slow, nli
    priority INTEGER DEFAULT 50,  -- Lower = higher priority
    slot TEXT NOT NULL,  -- gpu, browser_headful, network_client, cpu_nlp
    state TEXT DEFAULT 'pending',  -- pending, queued, running, completed, failed, cancelled
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

-- Embedding Cache
CREATE TABLE IF NOT EXISTS cache_embed (
    text_hash TEXT PRIMARY KEY,  -- SHA256 of text
    model_id TEXT NOT NULL,
    embedding_blob BLOB NOT NULL,  -- Binary embedding
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_embed_expires ON cache_embed(expires_at);

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
-- NOTE: This is added via schema.sql change; per user instruction DB is recreated, not migrated.
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
CREATE VIEW IF NOT EXISTS v_task_progress AS
SELECT 
    t.id as task_id,
    t.query,
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
-- Feedback & Override Tables ( / , 20)
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
    hypothesis TEXT NOT NULL,            -- NLI hypothesis snapshot (for training reproducibility)
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

-- ============================================================
-- Query A/B Testing (ADR-0010)
-- ============================================================

-- A/B test sessions
CREATE TABLE IF NOT EXISTS query_ab_tests (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    base_query TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    winner_variant_type TEXT,  -- original, notation, particle, order, combined
    winner_harvest_rate REAL,
    status TEXT DEFAULT 'pending',  -- pending, running, completed
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_ab_tests_task ON query_ab_tests(task_id);

-- A/B test variants
CREATE TABLE IF NOT EXISTS query_ab_variants (
    id TEXT PRIMARY KEY,
    ab_test_id TEXT NOT NULL,
    variant_type TEXT NOT NULL,  -- original, notation, particle, order, combined
    query_text TEXT NOT NULL,
    transformation TEXT,  -- Description of transformation applied
    result_count INTEGER DEFAULT 0,
    useful_fragments INTEGER DEFAULT 0,
    harvest_rate REAL,
    execution_time_ms INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ab_test_id) REFERENCES query_ab_tests(id)
);
CREATE INDEX IF NOT EXISTS idx_ab_variants_test ON query_ab_variants(ab_test_id);

-- High-yield query patterns cache
CREATE TABLE IF NOT EXISTS high_yield_queries (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,  -- notation, particle, order
    original_pattern TEXT NOT NULL,
    improved_pattern TEXT NOT NULL,
    improvement_ratio REAL,  -- (improved - original) / original
    sample_count INTEGER DEFAULT 1,
    confidence REAL DEFAULT 0.5,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_high_yield_pattern ON high_yield_queries(pattern_type);
CREATE INDEX IF NOT EXISTS idx_high_yield_confidence ON high_yield_queries(confidence);

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
CREATE VIEW IF NOT EXISTS v_task_metrics_summary AS
SELECT 
    t.id as task_id,
    t.query,
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

