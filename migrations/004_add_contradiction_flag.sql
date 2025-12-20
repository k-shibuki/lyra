-- Migration 004: Add contradiction flag and adoption status
-- For Phase 1: Improving transparency

-- Add is_contradiction flag to edges table
-- Used to mark edges that represent detected contradictions
ALTER TABLE edges ADD COLUMN is_contradiction BOOLEAN DEFAULT 0;

-- Index for efficient querying of contradiction edges
CREATE INDEX IF NOT EXISTS idx_edges_contradiction ON edges(is_contradiction) WHERE is_contradiction = 1;

-- Add adoption_status to claims table
-- Tracks whether a claim was adopted, rejected, or is still pending
-- Values: 'pending', 'adopted', 'not_adopted'
ALTER TABLE claims ADD COLUMN adoption_status TEXT DEFAULT 'pending';

-- Index for filtering by adoption status
CREATE INDEX IF NOT EXISTS idx_claims_adoption_status ON claims(adoption_status);
