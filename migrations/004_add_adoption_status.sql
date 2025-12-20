-- Migration 004: Add adoption status to claims
-- For Phase 1: Improving transparency

-- Add adoption_status to claims table
-- Tracks whether a claim was adopted, rejected, or is still pending
-- Values: 'pending', 'adopted', 'not_adopted'
ALTER TABLE claims ADD COLUMN adoption_status TEXT DEFAULT 'pending';

-- Index for filtering by adoption status
CREATE INDEX IF NOT EXISTS idx_claims_adoption_status ON claims(adoption_status);
