-- Migration 003: Add trust level columns to edges table
-- Per docs/EVIDENCE_SYSTEM.md Phase 2
--
-- Adds source_trust_level and target_trust_level columns to edges table
-- to enable high-reasoning AI to interpret contradiction relationships.

-- Add source trust level column (PRIMARY/GOVERNMENT/ACADEMIC/TRUSTED/LOW/UNVERIFIED/BLOCKED)
ALTER TABLE edges ADD COLUMN source_trust_level TEXT;

-- Add target trust level column
ALTER TABLE edges ADD COLUMN target_trust_level TEXT;

-- Create index for efficient querying of contradiction relationships
-- This enables fast lookup of edges by relation type and trust levels
CREATE INDEX IF NOT EXISTS idx_edges_trust_levels
    ON edges(relation, source_trust_level, target_trust_level);
