-- Migration: Add academic citation columns to edges table
-- Date: 2025-12-16
-- Description: Adds is_academic, is_influential, citation_context columns for J2 Academic API Integration

-- Add academic citation attributes to edges table
ALTER TABLE edges ADD COLUMN is_academic INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN is_influential INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN citation_context TEXT;

-- Add paper_metadata column to pages table
ALTER TABLE pages ADD COLUMN paper_metadata TEXT;
-- paper_metadata JSON structure:
-- {
--   "doi": "10.1234/example",
--   "authors": [{"name": "John Doe", "orcid": "0000-0001-2345-6789"}],
--   "year": 2024,
--   "venue": "Nature",
--   "citation_count": 42,
--   "reference_count": 25,
--   "is_open_access": true,
--   "source_api": "semantic_scholar"
-- }

-- Create index for academic citations
CREATE INDEX IF NOT EXISTS idx_edges_is_academic ON edges(is_academic);
CREATE INDEX IF NOT EXISTS idx_edges_is_influential ON edges(is_influential);

